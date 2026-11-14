#!/usr/bin/env python
"""Evaluate a user .tgz/.zip structure archive with an optimized DFThub functional."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from dfthub.pipeline.basis_presets import load_basis_preset
from dfthub.pipeline.compute_scheduler import TASK_THREADS, enter_task, molecular_pool, molecule_environment
from dfthub.pipeline.energy_extensions import (
    EnergyTaskOptions,
    PCM_METHOD_MAP,
    evaluate_molecule_energy,
    resolve_solvent_entry,
)
from dfthub.pipeline.refinement import file_hash, write_json
from dfthub.pipeline.run_ame418_srp import basis_size, extract_archive, parse_xyz


@dataclass
class EnergyMoleculeJob:
    xyz_path: Path
    name: str
    stage_dir: Path
    stage_out: Path
    result_json: Path
    natom: int
    nao: int | None
    identity: str


def _molecule_identity(xyz_path: Path, functional_path: Path, options: EnergyTaskOptions) -> str:
    _, _, atom_block, _ = parse_xyz(xyz_path)
    resolved_basis = load_basis_preset(atom_block, options.basis)
    payload = {
        "protocol": 2,
        "geometry": file_hash(xyz_path),
        "basis": resolved_basis,
        "functional": file_hash(functional_path),
        "options": options.to_dict(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _reusable_molecule_result(job: EnergyMoleculeJob) -> dict[str, Any] | None:
    if not job.result_json.is_file():
        return None
    try:
        data = json.loads(job.result_json.read_text())
        if data.get("identity") != job.identity or data.get("status") != "ok":
            return None
        energy = data.get("energy_hartree")
        if energy is None or not math.isfinite(float(energy)):
            return None
        result = dict(data)
        result.pop("identity", None)
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _discover_energy_jobs(
    user_xyz: Path,
    stage_root: Path,
    dataset_name: str,
    functional_path: Path,
    options: EnergyTaskOptions,
) -> list[EnergyMoleculeJob]:
    basis_tag = re.sub(r"[^a-z0-9]+", "-", options.basis).strip("-")
    opt_tag = options.signature()[:10]
    user_stage = stage_root / f"{dataset_name}_{basis_tag}_{opt_tag}_inputfile"
    if user_xyz.is_dir():
        xyz_dir = user_xyz
    else:
        xyz_dir = extract_archive(user_xyz, stage_root / f"_user_extract_{dataset_name}")

    xyz_files = sorted(xyz_dir.glob("*.xyz"))
    for xyz in xyz_files:
        _, _, atom_block, _ = parse_xyz(xyz)
        try:
            load_basis_preset(atom_block, options.basis)
        except Exception as exc:
            raise ValueError(f"{xyz.name}: {exc}") from exc

    user_stage.mkdir(parents=True, exist_ok=True)
    jobs: list[EnergyMoleculeJob] = []
    for xyz in xyz_files:
        name = xyz.stem
        _, _, _, natom = parse_xyz(xyz)
        identity = _molecule_identity(xyz, functional_path, options)
        jobs.append(
            EnergyMoleculeJob(
                xyz_path=xyz,
                name=name,
                stage_dir=user_stage,
                stage_out=user_stage / f"{name}.out",
                result_json=user_stage / f"{name}.energy.json",
                natom=natom,
                nao=basis_size(xyz, options.basis),
                identity=identity,
            )
        )
    return jobs


def _run_worker_cli(args: argparse.Namespace) -> None:
    options = EnergyTaskOptions.from_dict(json.loads(Path(args.worker_options).read_text()))
    result = evaluate_molecule_energy(
        xyz_path=Path(args.worker_xyz),
        functional_path=str(Path(args.cf22d_optimized).resolve()),
        options=options,
        stage_dir=Path(args.worker_stage),
        name=args.worker_name,
        threads=int(args.worker_threads),
    )
    result_with_id = dict(result, identity=args.worker_identity)
    write_json(Path(args.worker_result), result_with_id)


def _run_one_energy_job(
    job: EnergyMoleculeJob,
    functional_path: Path,
    options_file: Path,
    threads: int,
    python_exe: str,
) -> tuple[int, dict[str, Any] | None, float]:
    env = molecule_environment(threads)
    nthreads = str(threads)
    env.update({
        "AME_NUM_THREADS": nthreads,
        "OMP_NUM_THREADS": nthreads,
        "MKL_NUM_THREADS": nthreads,
        "OPENBLAS_NUM_THREADS": nthreads,
        "NUMEXPR_NUM_THREADS": nthreads,
        "HDF5_USE_FILE_LOCKING": "FALSE",
        "PYTHONUNBUFFERED": "1",
    })
    cmd = [
        python_exe,
        str(Path(__file__).resolve()),
        "--worker",
        "--cf22d-optimized", str(functional_path),
        "--worker-xyz", str(job.xyz_path),
        "--worker-options", str(options_file),
        "--worker-stage", str(job.stage_dir),
        "--worker-name", job.name,
        "--worker-identity", job.identity,
        "--worker-result", str(job.result_json),
        "--worker-threads", nthreads,
    ]
    t0 = time.time()
    with job.stage_out.open("w") as fh:
        rc = subprocess.run(cmd, cwd=job.stage_dir, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
    dt = time.time() - t0
    if rc == 0:
        return rc, _reusable_molecule_result(job), dt
    return rc, None, dt


def _tail_error_from_log(log_path: Path) -> str:
    if not log_path.is_file():
        return "energy calculation failed"
    try:
        lines = [line.strip() for line in log_path.read_text(errors="replace").splitlines() if line.strip()]
        for line in reversed(lines):
            if "Error:" in line or "RuntimeError:" in line or "ValueError:" in line:
                return line
        return lines[-1] if lines else "energy calculation failed"
    except OSError:
        return "energy calculation failed"


def _build_task_options(args: argparse.Namespace) -> EnergyTaskOptions:
    raw: dict[str, Any] = {}
    if args.config and Path(args.config).is_file():
        try:
            loaded = json.loads(Path(args.config).read_text())
            if isinstance(loaded, dict):
                raw.update(loaded)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"Invalid --config JSON file: {exc}") from exc

    if args.user_basis:
        raw["basis"] = args.user_basis
    if args.grid is not None:
        raw["grid_level"] = args.grid
    if args.no_d3:
        raw["with_d3"] = False
    if args.solvent_model is not None:
        raw["solvent_model"] = args.solvent_model
    if args.solvent_name is not None:
        raw["solvent_name"] = args.solvent_name
    if args.solvent_eps is not None:
        raw["solvent_eps"] = args.solvent_eps
    if args.optimize_geometry:
        raw["optimize_geometry"] = True
    if args.calc_thermo:
        raw["calc_thermo"] = True
    if args.temperature is not None:
        raw["temperature_k"] = args.temperature
    if args.pressure is not None:
        raw["pressure_pa"] = args.pressure
    if args.vib_model is not None:
        raw["vib_model"] = args.vib_model
    if args.qrrho_freq0 is not None:
        raw["qrrho_freq0"] = args.qrrho_freq0
    if args.freq_scale is not None:
        raw["freq_scale"] = args.freq_scale
    if args.solution_standard_state:
        raw["solution_standard_state"] = True

    default_basis = args.user_basis or raw.get("basis") or "def2-qzvp"
    return EnergyTaskOptions.from_dict(raw, default_basis=default_basis)


def _write_results_payload(
    output: Path,
    dataset: str,
    options: EnergyTaskOptions,
    jobs: list[EnergyMoleculeJob],
    results_by_name: dict[str, dict[str, Any]],
    failed: list[dict[str, str]],
    finished: bool,
) -> bool:
    failed_map = {item["name"]: item["error"] for item in failed}
    energies: list[dict[str, Any]] = []
    for job in jobs:
        if job.name in results_by_name:
            energies.append(results_by_name[job.name])
        elif job.name in failed_map:
            energies.append({
                "name": job.name,
                "energy_hartree": None,
                "status": "failed",
                "error": failed_map[job.name],
            })
        else:
            energies.append({
                "name": job.name,
                "energy_hartree": None,
                "status": "pending" if not finished else "failed",
            })

    complete = bool(energies) and all(row.get("status") == "ok" for row in energies)
    solvation_meta = None
    if options.solvent_model != "none":
        eps_val = options.solvent_eps
        if eps_val is None:
            try:
                _, eps_val = resolve_solvent_entry(options.solvent_name)
            except ValueError:
                eps_val = None
        solvation_meta = {
            "model": options.solvent_model,
            "method_label": PCM_METHOD_MAP.get(options.solvent_model, options.solvent_model.upper()),
            "solvent": options.solvent_name if options.solvent_eps is None else f"custom (eps={options.solvent_eps:g})",
            "eps": eps_val,
        }

    thermo_meta = None
    if options.calc_thermo:
        thermo_meta = {
            "temperature_k": options.temperature_k,
            "pressure_pa": options.pressure_pa,
            "vib_model": options.vib_model,
            "qrrho_freq0_cm1": options.qrrho_freq0,
            "freq_scale": options.freq_scale,
            "solution_standard_state": options.solution_standard_state,
        }

    payload = {
        "scope": "energy",
        "complete": complete,
        "basis": options.basis,
        "grid_level": options.grid_level,
        "with_d3": options.with_d3,
        "optimize_geometry": options.optimize_geometry,
        "calc_thermo": options.calc_thermo,
        "options": options.to_dict(),
        "solvation": solvation_meta,
        "thermochemistry": thermo_meta,
        "userDatasetTitle": f"{dataset} DFT energy results (SRP)",
        "userDatasetName": dataset,
        "molecularEnergies": energies,
        "failed": failed,
        "updated_at": time.time(),
    }
    result_path = output / "SinglePointResults.energy.json"
    write_json(result_path, payload)
    if output.parent.name == "energy_input" and output.parent.parent.is_dir():
        try:
            write_json(output.parent.parent / "SinglePointResults.energy.json", payload)
        except OSError:
            pass
    return complete


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker-xyz", help=argparse.SUPPRESS)
    parser.add_argument("--worker-options", help=argparse.SUPPRESS)
    parser.add_argument("--worker-stage", help=argparse.SUPPRESS)
    parser.add_argument("--worker-name", help=argparse.SUPPRESS)
    parser.add_argument("--worker-identity", help=argparse.SUPPRESS)
    parser.add_argument("--worker-result", help=argparse.SUPPRESS)
    parser.add_argument("--worker-threads", type=int, default=8, help=argparse.SUPPRESS)

    parser.add_argument("--cf22d-optimized", required=True)
    parser.add_argument("--output")
    parser.add_argument("--user-xyz")
    parser.add_argument("--user-basis", default="")
    parser.add_argument("--grid", type=int, default=None)
    parser.add_argument("--no-d3", action="store_true")
    parser.add_argument("--solvent-model", default=None)
    parser.add_argument("--solvent-name", default=None)
    parser.add_argument("--solvent-eps", type=float, default=None)
    parser.add_argument("--optimize-geometry", action="store_true")
    parser.add_argument("--calc-thermo", action="store_true")
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--pressure", type=float, default=None)
    parser.add_argument("--vib-model", default=None)
    parser.add_argument("--qrrho-freq0", type=float, default=None)
    parser.add_argument("--freq-scale", type=float, default=None)
    parser.add_argument("--solution-standard-state", action="store_true")
    parser.add_argument("--config", default=None, help="Path to energy_config.json")
    parser.add_argument("--cores", type=int, default=TASK_THREADS)
    parser.add_argument("--max-threads", type=int, default=16)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.worker:
        _run_worker_cli(args)
        return

    if not args.output or not args.user_xyz:
        parser.error("--output and --user-xyz are required")

    args.cores = min(max(1, args.cores), TASK_THREADS)
    args.max_threads = min(max(1, args.max_threads), 16)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    functional_path = Path(args.cf22d_optimized).resolve()
    options = _build_task_options(args)

    stage = output / "energy_srp"
    stage.mkdir(parents=True, exist_ok=True)
    options_file = stage / "active_energy_options.json"
    write_json(options_file, options.to_dict())

    dataset = Path(args.user_xyz).name
    for suffix in (".tar.gz", ".tgz", ".zip"):
        if dataset.endswith(suffix):
            dataset = dataset[: -len(suffix)]
            break

    jobs = _discover_energy_jobs(Path(args.user_xyz).resolve(), stage, dataset, functional_path, options)
    if not jobs:
        raise SystemExit("No .xyz molecules were found in the uploaded archive")

    enter_task(str(output), args.cores)
    print(
        f"[EnergyTask] dataset={dataset} molecules={len(jobs)} basis={options.basis} "
        f"grid={options.grid_level} d3={options.with_d3} solvent={options.solvent_model}"
        + (f"({options.solvent_name if options.solvent_eps is None else options.solvent_eps})" if options.solvent_model != "none" else "")
        + f" opt={options.optimize_geometry} thermo={options.calc_thermo}",
        flush=True,
    )

    results_by_name: dict[str, dict[str, Any]] = {}
    selected: list[EnergyMoleculeJob] = []
    for job in jobs:
        if args.force:
            job.result_json.unlink(missing_ok=True)
            selected.append(job)
        else:
            cached = _reusable_molecule_result(job)
            if cached is not None:
                results_by_name[job.name] = cached
            else:
                selected.append(job)

    failed: list[dict[str, str]] = []
    _write_results_payload(output, dataset, options, jobs, results_by_name, failed, finished=False)

    if selected:
        def run(job: EnergyMoleculeJob, threads: int):
            return _run_one_energy_job(job, functional_path, options_file, threads, args.python)

        for done_idx, (job, result, error) in enumerate(
            molecular_pool(
                selected,
                lambda job: job.natom,
                run,
                args.cores,
                args.max_threads,
                nao=lambda job: job.nao or max(1, job.natom * 20),
            ),
            1,
        ):
            rc, mol_result, elapsed = result if error is None else (-1, None, 0.0)
            if rc != 0 or mol_result is None:
                err_msg = str(error) if error is not None else _tail_error_from_log(job.stage_out)
                failed.append({"name": job.name, "error": err_msg})
                print(f"[{done_idx}/{len(selected)}] {job.name}: FAILED ({err_msg})", flush=True)
            else:
                results_by_name[job.name] = mol_result
                e_str = f"E={mol_result['energy_hartree']:.8f} Eh"
                if mol_result.get("g_tot_hartree") is not None:
                    e_str += f"  G={mol_result['g_tot_hartree']:.8f} Eh"
                print(f"[{done_idx}/{len(selected)}] {job.name}: OK ({e_str}, {elapsed:.1f}s)", flush=True)
            _write_results_payload(output, dataset, options, jobs, results_by_name, failed, finished=False)

    complete = _write_results_payload(output, dataset, options, jobs, results_by_name, failed, finished=True)
    result_path = output / "SinglePointResults.energy.json"
    print(f"Results written to {result_path}", flush=True)
    if not complete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
