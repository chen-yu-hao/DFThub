#!/usr/bin/env python
"""Run Input or AME418 self-consistent energies with an optimized CF22D-SRP functional.

Uses existing .chk files from a prior CF22D run as starting points, applies the
user-optimized SRP functional (CF22D_optimized.py), then computes MAE/RMSE vs
Database2 reference data and writes SinglePointResults.json.

Thread allocation per job is based on atom count (max 16 per job, total budget
defaults to 56 threads).  Small molecules run with fewer threads so more jobs can
run in parallel.

Usage:
    python run_ame418_srp.py \
        --cf22d-optimized /path/to/CF22D_optimized.py \
        --output /path/to/weight_N \
        --scope ame418 \
        --cores 56
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import tarfile
import textwrap
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from dfthub.pipeline.compute_scheduler import (TASK_THREADS, enter_task, molecular_pool,
                               molecule_environment, thread_environment,
                               threads_for_basis, basis_size)

os.environ.update(thread_environment(1))

from dfthub.pipeline.refinement import (correct_input_energies, prepare_input_snapshot,
                        publish_input_snapshot, write_json)
from dfthub.pipeline.scf_resume import job_identity, completed_energy, descriptor_valid, progress_path

from dfthub.pipeline.basis_presets import (
    DEFAULT_BASIS,
    SUPPORTED_BASIS,
    load_basis_preset,
    resolve_basis_sources,
)


from dfthub.paths import optimizer_dir, data_dir
AME418_ROOT = Path(os.environ.get("DFTHUB_AME418_ROOT", str(data_dir() / "AME418")))
REF_ROOT = optimizer_dir() / "Database2/ref"
HARTREE_TO_KCAL = 627.509

ENERGY_RE = re.compile(r"(?:E\(total\)|FINAL ENERGY \(Hartree\):)\s*=?\s*(-?\d+\.\d+)")

SPECIAL_FINAL_CHKS = {
    ("MR-TM-BE11_inputfile", "Cr2"): "Cr2_uks_bs.chk",
    ("Fe2_inputfile", "Fe"): "Fe_stab_newton.chk",
    ("Fe2_inputfile", "Fe2_9"): "Fe2_9_stab.chk",
}

DATASET_SPECS = {
    "2pIsoE4": {"refs": ("2pIsoE4_ref",), "energy_datasets": ("2pIsoE4",)},
    "3dAEE7": {"refs": ("3dEE8_ref",), "energy_datasets": ("3dAEE7",)},
    "4dAEE5": {"refs": ("4dAEE5_ref",), "energy_datasets": ("4dAEE5",)},
    "4pIsoE4": {"refs": ("4pIsoE4_ref",), "energy_datasets": ("4pIsoE4",)},
    "AE17": {"refs": ("AE17_ref",), "energy_datasets": ("AE17",)},
    "DC9": {"refs": ("DC9_ref",), "energy_datasets": ("DC9",)},
    "EA13": {"refs": ("EA13_ref",), "energy_datasets": ("EA13",)},
    "HC7": {"refs": ("HC7_ref",), "energy_datasets": ("HC7",)},
    "HTBH38": {"refs": ("HTBH38_ref",), "energy_datasets": ("HTBH38",)},
    "IP23": {"refs": ("IP23_ref",), "energy_datasets": ("IP23",)},
    "IsoL6-noopt": {"refs": ("IsoL6_ref",), "energy_datasets": ("IsoL6-noopt",)},
    "MR-MGM-BE4": {"refs": ("MR-MGM-BE4_ref",), "energy_datasets": ("MR-MGM-BE4",)},
    "MR-MGN-BE17": {"refs": ("MR-MGN-BE17_ref",), "energy_datasets": ("MR-MGN-BE17",)},
    "MR-TML-BE12": {
        "refs": ("MR-TML-BE12_ref",),
        "energy_datasets": ("MR-TM-BE11", "Fe2"),
    },
    "MR-TMD-BE3": {
        "refs": ("MR-TMD-BE3_ref",),
        "energy_datasets": ("MR-TM-BE11", "Fe2"),
    },
    "NCCE30": {"refs": ("NCCE30_ref",), "energy_datasets": ("NCCE34",)},
    "NGA21": {"refs": ("NGD21_ref",), "energy_datasets": ("NGA21",)},
    "NHTBH38": {
        "refs": ("NHTBH38_ref",),
        "energy_datasets": ("NHTBH38",),
        "aliases": {"TS8": "TS7", "TS10": "TS9", "TS12": "TS11", "TS14": "TS13"},
    },
    "PA8": {"refs": ("PA8_ref",), "energy_datasets": ("PA8",)},
    "SMAE4": {"refs": ("SMAE3_ref",), "energy_datasets": ("SMAE4",)},
    "SR-MGM-BE9": {"refs": ("SR-MGM-BE8_ref",), "energy_datasets": ("SR-MGM-BE9",)},
    "SR-MGN-BE107": {"refs": ("SR-MGN-BE107_ref",), "energy_datasets": ("SR-MGN-BE107",)},
    "SR-TML-BE11": {"refs": ("SR-TML-BE11_ref",), "energy_datasets": ("SR-TM-BE16",)},
    "SR-TMD-BE4": {"refs": ("SR-TMD-BE4_ref",), "energy_datasets": ("SR-TM-BE16",)},
    "pEE5": {"refs": ("pAEE5_ref",), "energy_datasets": ("pEE5",)},
    "pTC13": {"refs": ("πIE3_ref", "πPa10_ref"), "energy_datasets": ("pTC13",)},
}


# ---------------------------------------------------------------------------
# Job data
# ---------------------------------------------------------------------------

NATOM_RE = re.compile(r"\[INPUT\] num\. atoms\s*=\s*(\d+)")
FORK_NAME_RE = re.compile(r"fork-[1-9]\d*")
RUN_COMPONENT_RE = re.compile(r"(?:weight_\d+|fork-[1-9]\d*)")
SNAPSHOT_ID_RE = re.compile(r"[a-f0-9]{32}")


@dataclass(frozen=True)
class InputCheckpointSource:
    """Read-only source selected for an Input SCF restart."""

    kind: str
    root: Path
    snapshot_id: str | None = None
    parent_run: str | None = None


@dataclass(frozen=True)
class Job:
    source_py: Path
    source_chk: Path
    dataset_dir: str
    dataset: str
    name: str
    stage_dir: Path
    stage_py: Path
    stage_chk: Path
    stage_out: Path
    natom: int = 1
    initial_chk: Path | None = None
    nao: int | None = None
    basis: str = ""


def job_threads(job, max_threads=16):
    return threads_for_basis(job.nao or max(1, job.natom * 20), max_threads)


def reusable_user_energy(job, grid, functional):
    """Validate completed artifacts; adopt only proven, matching old snapshots."""
    if not job.basis:
        return None
    identity = job_identity(job.source_py, job.basis, functional, grid)
    energy = completed_energy(job.stage_chk, identity, grid)
    if energy is not None or progress_path(job.stage_chk).exists():
        return energy
    # Historic training results live inside a source-verified Input snapshot.
    # Shared legacy test_srp results lack that provenance and are not adopted.
    manifest = job.stage_dir.parent / 'manifest.json'
    try:
        from dfthub.pipeline.refinement import file_hash
        from pyscf.scf import chkfile
        metadata = json.loads(manifest.read_text())
        if (metadata['functional_sha256'] != file_hash(functional) or
                metadata['grid_level'] != grid or metadata['basis'] != job.basis):
            return None
        energy = parse_energy(job.stage_out)
        if energy is None or not descriptor_valid(job.stage_chk, grid):
            return None
        text = job.stage_out.read_text()
        if not re.search(r'^  stability round \d+: internal=True$', text, re.M):
            return None
        validate_input_checkpoint(job.source_py, job.stage_chk, job.basis)
        _, data = chkfile.load_scf(str(job.stage_chk))
        details = json.loads(job.stage_chk.with_suffix('.desc.json').read_text())
        if abs(data['e_tot'] - energy) > 1e-8 or abs(details['energy'] - energy) > 1e-8:
            return None
        stable = job.stage_chk.with_suffix('.stable.chk')
        shutil.copy2(job.stage_chk, stable)
        write_json(progress_path(job.stage_chk), {
            'identity': identity, 'stage': 'complete', 'energy': energy, 'rounds': 1,
            'checkpoint_sha256': file_hash(stable),
            'hashes': {'checkpoint': file_hash(job.stage_chk),
                       'descriptor': file_hash(job.stage_chk.with_suffix('.desc.npy')),
                       'details': file_hash(job.stage_chk.with_suffix('.desc.json'))},
        })
        return energy
    except (OSError, ValueError, KeyError, TypeError):
        return None


def get_natom(source_py: Path) -> int:
    """Read atom count from the original .out file next to the source .py."""
    out = source_py.with_suffix(".out")
    try:
        for line in out.open():
            m = NATOM_RE.search(line)
            if m:
                return int(m.group(1))
    except OSError:
        pass
    return 1


# ---------------------------------------------------------------------------
# Energy parsing
# ---------------------------------------------------------------------------

def parse_energy(path: Path) -> float | None:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    matches = ENERGY_RE.findall(text)
    return float(matches[-1]) if matches else None


def has_result(path: Path) -> bool:
    return parse_energy(path) is not None


# ---------------------------------------------------------------------------
# Input checkpoint lineage
# ---------------------------------------------------------------------------

def _output_root(output_dir: Path) -> Path:
    """Return the Work/<user>/<job>/output directory for a run output."""
    output_dir = output_dir.resolve()
    for ancestor in (output_dir, *output_dir.parents):
        if ancestor.name == "output":
            return ancestor
    raise ValueError(f"run output is not below an output directory: {output_dir}")


def _safe_run_path(output_root: Path, run_id: str) -> Path:
    """Resolve a generated run id while rejecting path traversal."""
    parts = Path(run_id).parts
    if not parts or any(not RUN_COMPONENT_RE.fullmatch(part) for part in parts):
        raise ValueError(f"invalid parent run id: {run_id!r}")
    candidate = (output_root / Path(*parts)).resolve()
    root = output_root.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"parent run escapes output root: {run_id!r}")
    return candidate


def _read_manifest(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read checkpoint snapshot manifest {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"checkpoint snapshot manifest is not an object: {path}")
    return payload


def _manifest_matches_input(payload: dict, snapshot_metadata: dict) -> bool:
    return (
        payload.get("complete") is True
        and payload.get("geometry_sha256") == snapshot_metadata.get("geometry_sha256")
        and payload.get("basis") == snapshot_metadata.get("basis")
    )


def _checkpoint_snapshot_candidates(output_dir: Path, snapshot_metadata: dict):
    root = output_dir / "input_srp"
    if not root.is_dir():
        return []
    candidates = []
    for manifest_path in root.glob("*/manifest.json"):
        snapshot_id = manifest_path.parent.name
        if not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
            continue
        try:
            payload = _read_manifest(manifest_path)
        except ValueError:
            continue
        if not _manifest_matches_input(payload, snapshot_metadata):
            continue
        created = payload.get("created_at", 0)
        try:
            created = float(created)
        except (TypeError, ValueError):
            created = manifest_path.stat().st_mtime
        candidates.append((created, manifest_path.parent, snapshot_id))
    return sorted(candidates, key=lambda item: (item[0], item[2]), reverse=True)


def resolve_input_checkpoint_source(output_dir: Path, snapshot_metadata: dict) -> InputCheckpointSource:
    """Select the immutable checkpoint lineage for a user Input calculation.

    A non-fork run always starts from the initial density checkpoint created by
    weight_0. A fork first tries its latest complete Input snapshot, then the
    exact parent snapshot recorded in run.json.
    """
    output_dir = output_dir.resolve()
    recorded = snapshot_metadata.get('initial_guess_source')
    if recorded and recorded.get('mode') == 'previous_input':
        snapshot_id = recorded.get('snapshot_id')
        if not isinstance(snapshot_id, str) or not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
            raise ValueError('Invalid saved initial checkpoint source')
        parent = recorded.get('parent_run')
        source_output = _safe_run_path(_output_root(output_dir), parent) if parent else output_dir
        snapshot = source_output / 'input_srp' / snapshot_id
        if not _manifest_matches_input(_read_manifest(snapshot / 'manifest.json'), snapshot_metadata):
            raise ValueError('Saved initial checkpoint source no longer matches Input')
        return InputCheckpointSource('previous_input', snapshot.resolve(), snapshot_id, parent)
    if not FORK_NAME_RE.fullmatch(output_dir.name):
        root = _output_root(output_dir) / "weight_0" / "work"
        if not root.is_dir():
            raise FileNotFoundError(
                f"initial density checkpoint directory is missing: {root}"
            )
        return InputCheckpointSource("initial_density", root.resolve())

    current = _checkpoint_snapshot_candidates(output_dir, snapshot_metadata)
    if current:
        _, snapshot, snapshot_id = current[0]
        return InputCheckpointSource("previous_input", snapshot.resolve(), snapshot_id)

    run_file = output_dir / "run.json"
    if not run_file.is_file():
        raise FileNotFoundError(f"fork metadata is missing: {run_file}")
    try:
        run = json.loads(run_file.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read fork metadata {run_file}: {exc}") from exc
    parent_id = run.get("parent")
    snapshot_id = run.get("descriptor_snapshot_id")
    if not isinstance(parent_id, str) or not isinstance(snapshot_id, str) or not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise ValueError(f"fork metadata has no valid parent snapshot: {run_file}")
    output_root = _output_root(output_dir)
    parent_output = _safe_run_path(output_root, parent_id)
    snapshot = parent_output / "input_srp" / snapshot_id
    manifest_path = snapshot / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"parent Input snapshot manifest is missing: {manifest_path}")
    manifest = _read_manifest(manifest_path)
    if not _manifest_matches_input(manifest, snapshot_metadata):
        raise ValueError(
            f"parent Input snapshot {snapshot_id} does not match the current geometry or basis"
        )
    return InputCheckpointSource("previous_input", snapshot.resolve(), snapshot_id, parent_id)


def test_checkpoint_sources(output_dir: Path, input_source: InputCheckpointSource):
    """Use Test densities from the selected Input lineage, then initial Test."""
    sources = []
    if input_source.kind == 'previous_input':
        sources.append(InputCheckpointSource('previous_test', input_source.root / 'test_srp',
                                              input_source.snapshot_id, input_source.parent_run))
    sources.append(InputCheckpointSource('initial_test', _output_root(output_dir) / 'weight_0/test_work'))
    return sources


def matching_test_checkpoint(xyz_path: Path, basis_preset: str, sources):
    """A missing/mismatched parent Test molecule must never supply a density."""
    for source in sources:
        try:
            checkpoint = _checkpoint_for_molecule(source.root, xyz_path.stem)
            validate_input_checkpoint(xyz_path, checkpoint, basis_preset)
        except (OSError, ValueError) as exc:
            print(f'Test checkpoint unavailable ({source.kind}, {xyz_path.stem}): {exc}', flush=True)
            continue
        print(f'Test initial density ({xyz_path.stem}): {source.kind} checkpoint={checkpoint}', flush=True)
        return checkpoint
    print(f'Test initial density ({xyz_path.stem}): minao; no matching checkpoint', flush=True)
    return None


def _checkpoint_for_molecule(root: Path, name: str) -> Path:
    """Find exactly one checkpoint for a molecule below a selected source."""
    direct = [root / f"{name}.pychk", root / f"{name}.chk"]
    matches = {path.resolve() for path in direct if path.is_file() and path.stat().st_size > 0}
    if not matches:
        for suffix in (".pychk", ".chk"):
            matches.update(
                path.resolve()
                for path in root.rglob(f"{name}{suffix}")
                if path.is_file() and path.stat().st_size > 0
            )
    if not matches:
        raise FileNotFoundError(f"checkpoint for {name} is missing below {root}")
    if len(matches) != 1:
        choices = ", ".join(str(path) for path in sorted(matches))
        raise ValueError(f"multiple checkpoints for {name} below {root}: {choices}")
    return next(iter(matches))


def validate_input_checkpoint(xyz_path: Path, checkpoint: Path, basis_preset: str) -> None:
    """Validate a checkpoint against a user molecule before SCF starts."""
    from pyscf import dft, gto
    from pyscf.scf import chkfile as scf_chkfile
    import numpy as np

    charge, spin, atom_block, _ = parse_xyz(xyz_path)
    basis, ecp = resolve_basis_sources(atom_block, basis_preset)
    mol = gto.M(atom=atom_block, basis=basis, ecp=ecp, charge=charge, spin=spin, verbose=0)
    try:
        chk_mol, record = scf_chkfile.load_scf(str(checkpoint))
    except Exception as exc:
        raise ValueError(f"cannot load checkpoint {checkpoint}: {exc}") from exc
    if not isinstance(record, dict) or record.get("mo_coeff") is None or record.get("mo_occ") is None:
        raise ValueError(f"checkpoint has no SCF orbitals or occupations: {checkpoint}")
    if (
        chk_mol.charge != mol.charge
        or chk_mol.spin != mol.spin
        or chk_mol.nelectron != mol.nelectron
        or chk_mol.nao_nr() != mol.nao_nr()
        or chk_mol._ecp != mol._ecp
        or not np.array_equal(chk_mol.atom_charges(), mol.atom_charges())
        or not np.allclose(chk_mol.atom_coords(), mol.atom_coords(), rtol=0, atol=1e-7)
        or not gto.mole.same_mol(chk_mol, mol, cmp_basis=True)
    ):
        raise ValueError(f"checkpoint molecule/basis is incompatible: {checkpoint}")
    mf = dft.RKS(mol) if spin == 0 else dft.UKS(mol)
    try:
        dm = mf.make_rdm1(record["mo_coeff"], record["mo_occ"])
    except Exception as exc:
        raise ValueError(f"checkpoint density cannot be constructed: {checkpoint}: {exc}") from exc
    expected_shape = (mol.nao_nr(), mol.nao_nr()) if spin == 0 else (2, mol.nao_nr(), mol.nao_nr())
    if dm is None or np.shape(dm) != expected_shape or not np.all(np.isfinite(dm)):
        raise ValueError(f"checkpoint density is invalid: {checkpoint}")


# ---------------------------------------------------------------------------
# Staging & patching
# ---------------------------------------------------------------------------

def patch_helper_srp(text: str) -> str:
    """Patch ame_helper.py to support SRP functional injection via env var."""
    text = memory_override(text)
    marker = "# AME_SRP_FUNCTIONAL override inserted by run_ame418_srp.py"
    if marker in text:
        return text

    # Also apply the grid-level override from run_pyscf_grid_from_chk.py
    grid_marker = "# AME_GRID_LEVEL override inserted by run_pyscf_grid_from_chk.py"
    if grid_marker not in text:
        old_grid = "    mf.grids.level = grids\n"
        new_grid = (
            f"    {grid_marker}\n"
            '    grids = int(os.environ.get("AME_GRID_LEVEL", grids))\n'
            "    mf.grids.level = grids\n"
        )
        if old_grid in text:
            text = text.replace(old_grid, new_grid, 1)

    # Insert SRP functional override after mf.xc is set in _make_mf
    old = "    mf.xc = XC_ALIASES.get(xc, xc)\n"
    new = (
        "    mf.xc = XC_ALIASES.get(xc, xc)\n"
        f"    {marker}\n"
        '    _srp = os.environ.get("AME_SRP_FUNCTIONAL")\n'
        "    if _srp and os.path.exists(_srp):\n"
        "        import importlib.util as _ilu\n"
        '        _spec = _ilu.spec_from_file_location("cf22d_srp", _srp)\n'
        "        _mod = _ilu.module_from_spec(_spec)\n"
        "        _spec.loader.exec_module(_mod)\n"
        "        _mod.register_cf22d_srp(mf)\n"
    )
    if old not in text:
        return text
    return text.replace(old, new, 1)


GRID_ASSIGN_RE = re.compile(r"(^\s*mf\.grids\.level\s*=\s*)(\d+)\s*$", re.MULTILINE)


def memory_override(text):
    return re.sub(r'\bmax_memory\s*=\s*(\d+)',
                  lambda match: 'max_memory=int(os.environ.get("DFTHUB_MAXMEM", "' + match[1] + '"))', text)


def patch_job_py(text: str, dataset_dir: str, name: str) -> str:
    """Patch a molecule .py script to read grid level from env."""
    text = memory_override(text)
    def grid_repl(match: re.Match[str]) -> str:
        return f'{match.group(1)}int(os.environ.get("AME_GRID_LEVEL", "{match.group(2)}"))'
    text = GRID_ASSIGN_RE.sub(grid_repl, text)

    # Inject SRP override for scripts that set mf.xc directly (bypassing _make_mf)
    direct_xc = "    mf.xc = H.XC_ALIASES['CF22D']\n"
    if direct_xc in text:
        srp_inject = (
            '    _srp = os.environ.get("AME_SRP_FUNCTIONAL")\n'
            "    if _srp:\n"
            "        import importlib.util as _ilu\n"
            '        _spec = _ilu.spec_from_file_location("cf22d_srp", _srp)\n'
            "        _mod = _ilu.module_from_spec(_spec)\n"
            "        _spec.loader.exec_module(_mod)\n"
            "        _mod.register_cf22d_srp(mf)\n"
        )
        text = text.replace(direct_xc, direct_xc + srp_inject)

    if (dataset_dir, name) == ("MR-TM-BE11_inputfile", "Cr2"):
        text = text.replace(
            "from pyscf.scf import addons\n",
            "from pyscf.scf import addons, chkfile as scf_chkfile\n",
            1,
        )
        hook = '''

def dm_from_env_chk(mf):
    chk = os.environ.get("AME_CHKFILE")
    if not chk or not os.path.exists(chk):
        return None
    try:
        _mol_chk, rec = scf_chkfile.load_scf(chk)
        return mf.make_rdm1(rec["mo_coeff"], rec["mo_occ"])
    except Exception as err:
        print("WARNING: failed to load AME_CHKFILE %s: %s" % (chk, err), flush=True)
        return None
'''
        if "def dm_from_env_chk(mf):" not in text:
            text = text.replace("\nrks = setup_rks(", hook + "\nrks = setup_rks(", 1)
        text = text.replace(
            "mf.kernel(dm0=bs_guess(mol))",
            "dm0 = dm_from_env_chk(mf)\nif dm0 is None:\n    dm0 = bs_guess(mol)\nmf.kernel(dm0=dm0)",
            1,
        )
    return text


def copy_text_with_patch(src: Path, dst: Path, patcher) -> None:
    text = src.read_text(errors="replace")
    dst.write_text(patcher(text))
    shutil.copystat(src, dst)


def stage_job(job: Job) -> None:
    job.stage_dir.mkdir(parents=True, exist_ok=True)
    copy_text_with_patch(
        job.source_py, job.stage_py,
        lambda text: patch_job_py(text, job.dataset_dir, job.name),
    )
    helper_src = job.source_py.parent / "ame_helper.py"
    helper_dst = job.stage_dir / "ame_helper.py"
    if helper_src.exists():
        copy_text_with_patch(helper_src, helper_dst, patch_helper_srp)
    shutil.copy2(job.source_chk, job.stage_chk)
    special_chk = SPECIAL_FINAL_CHKS.get((job.dataset_dir, job.name))
    if special_chk:
        shutil.copy2(job.source_chk, job.stage_dir / special_chk)


def sync_special_chk(job: Job) -> None:
    special_chk = SPECIAL_FINAL_CHKS.get((job.dataset_dir, job.name))
    if not special_chk:
        return
    special_path = job.stage_dir / special_chk
    if special_path.exists() and special_path.stat().st_size > 0:
        shutil.copy2(special_path, job.stage_chk)


# ---------------------------------------------------------------------------
# Job discovery
# ---------------------------------------------------------------------------

def discover(out_root: Path) -> tuple[list[Job], list[tuple[Path, str]]]:
    jobs: list[Job] = []
    skipped: list[tuple[Path, str]] = []
    for source_py in sorted(AME418_ROOT.glob("*_inputfile/*.py")):
        if source_py.name == "ame_helper.py":
            continue
        dataset_dir = source_py.parent.name
        dataset = dataset_dir.removesuffix("_inputfile")
        name = source_py.stem
        source_chk = source_py.with_suffix(".chk")
        if not source_chk.exists() or source_chk.stat().st_size == 0:
            skipped.append((source_py, "missing chk"))
            continue
        stage_dir = out_root / dataset_dir
        natom = get_natom(source_py)
        try:
            from pyscf.scf import chkfile
            nao = chkfile.load_mol(str(source_chk)).nao_nr()
        except (OSError, ValueError, KeyError):
            nao = None
        jobs.append(Job(
            source_py=source_py,
            source_chk=source_chk,
            dataset_dir=dataset_dir,
            dataset=dataset,
            name=name,
            stage_dir=stage_dir,
            stage_py=stage_dir / source_py.name,
            stage_chk=stage_dir / f"{name}.chk",
            stage_out=stage_dir / f"{name}.out",
            natom=natom,
            nao=nao,
        ))
    return jobs, skipped


# ---------------------------------------------------------------------------
# Run one job
# ---------------------------------------------------------------------------

def run_one(job: Job, grid: int, srp_path: str, threads: int,
            python: str) -> tuple[int, float | None, float]:
    env = molecule_environment(threads)
    nthreads = str(threads)
    env.update({
        "AME_NUM_THREADS": nthreads,
        "OMP_NUM_THREADS": nthreads,
        "MKL_NUM_THREADS": nthreads,
        "OPENBLAS_NUM_THREADS": nthreads,
        "NUMEXPR_NUM_THREADS": nthreads,
        "HDF5_USE_FILE_LOCKING": "FALSE",
        "AME_BASIS_DIR": str(AME418_ROOT / "basis"),
        "AME_CHKFILE": str(job.stage_chk),
        "AME_GRID_LEVEL": str(grid),
        "AME_SRP_FUNCTIONAL": srp_path,
    })
    cmd = [python, job.stage_py.name]
    t0 = time.time()
    with job.stage_out.open("w") as fh:
        rc = subprocess.run(cmd, cwd=job.stage_dir, env=env,
                            stdout=fh, stderr=subprocess.STDOUT).returncode
    dt = time.time() - t0
    if rc == 0:
        sync_special_chk(job)
    return rc, parse_energy(job.stage_out), dt


# ---------------------------------------------------------------------------
# User dataset (xyz → PySCF script → single-point energy)
# ---------------------------------------------------------------------------

def parse_xyz(path: Path):
    with path.open() as f:
        lines = f.read().strip().splitlines()
    natom = int(lines[0].split()[0])
    charge, spin = 0, 0
    fields = lines[1].split()
    if len(fields) >= 2:
        try:
            charge = int(fields[0])
            mult = int(fields[1])
            spin = mult - 1
        except ValueError:
            pass
    atom_block = "\n".join(lines[2 : 2 + natom])
    return charge, spin, atom_block, natom


def generate_user_script(xyz_path: Path, basis_preset: str = DEFAULT_BASIS) -> str:
    charge, spin, atom_block, _ = parse_xyz(xyz_path)
    ks = "RKS" if spin == 0 else "UKS"
    basis, ecp = resolve_basis_sources(atom_block, basis_preset)
    basis_setup = (
        f"_basis_sources = {basis!r}\n"
        f"_basis = {{element: gto.basis.load(source, element) "
        f"for element, source in _basis_sources.items()}}\n"
    )
    if ecp:
        ecp_setup = (
            f"_ecp_sources = {ecp!r}\n"
            f"_ecp = {{element: gto.basis.load_ecp(source, element) "
            f"for element, source in _ecp_sources.items()}}\n"
        )
    else:
        ecp_setup = f"_ecp = {ecp!r}\n"
    return (
        f'import os, sys\n'
        f'from pyscf import gto, dft, lib\n'
        f'from pyscf.scf import chkfile as _scf_chkfile\n'
        f'lib.num_threads(int(os.environ.get("AME_NUM_THREADS", "8")))\n'
        f'{basis_setup}'
        f'{ecp_setup}'
        f'mol = gto.M(\n'
        f'    atom={atom_block!r},\n'
        f'    basis=_basis,\n'
        f'    ecp=_ecp,\n'
        f'    charge={charge},\n'
        f'    spin={spin},\n'
        f'    verbose=4,\n'
        f'    max_memory=int(os.environ.get("DFTHUB_MAXMEM", "6000")),\n'
        f')\n'
        f'mf = dft.{ks}(mol)\n'
        f'mf.grids.level = int(os.environ.get("AME_GRID_LEVEL", "6"))\n'
        f'mf.conv_tol = 1e-8\n'
        f'mf.max_cycle = 500\n'
        f'_chkfile_path = os.environ.get("AME_CHKFILE", {(xyz_path.stem + ".chk")!r})\n'
        f'# Stage checkpoints are written atomically by scf_resume.\n'
        f'mf.chkfile = None\n'
        f'_srp = os.environ.get("AME_SRP_FUNCTIONAL")\n'
        f'if _srp:\n'
        f'    import importlib.util as _ilu\n'
        f'    _spec = _ilu.spec_from_file_location("cf22d_srp", _srp)\n'
        f'    _mod = _ilu.module_from_spec(_spec)\n'
        f'    _spec.loader.exec_module(_mod)\n'
        f'    _mod.register_cf22d_srp(mf)\n'
        f'else:\n'
        f'    mf.xc = "CF22D,CF22D"\n'
        f'_initial_chk = os.environ.get("DFTHUB_INITIAL_CHKFILE")\n'
        f'_dm0 = None\n'
        f'if _initial_chk:\n'
        f'    try:\n'
        f'        _chk_mol, _chk_record = _scf_chkfile.load_scf(_initial_chk)\n'
        f'        if (_chk_mol.charge != mol.charge or _chk_mol.spin != mol.spin or\n'
        f'                _chk_mol.nelectron != mol.nelectron or\n'
        f'                _chk_mol.nao_nr() != mol.nao_nr() or\n'
        f'                not gto.mole.same_mol(_chk_mol, mol, cmp_basis=True)):\n'
        f'            raise RuntimeError("checkpoint molecule/basis is incompatible")\n'
        f'        _dm0 = mf.make_rdm1(_chk_record["mo_coeff"], _chk_record["mo_occ"])\n'
        f'        print("  initial guess  = checkpoint: %s" % _initial_chk, flush=True)\n'
        f'    except Exception as _err:\n'
        f'        raise RuntimeError("Input checkpoint could not be used: %s" % _err) from _err\n'
        f'else:\n'
        f'    print("  initial guess  = minao", flush=True)\n'
        f'from scf_resume import run_staged_scf\n'
        f'e = run_staged_scf(mf, _mod, _chkfile_path, os.environ["DFTHUB_SCF_IDENTITY"], dm0=_dm0)\n'
        f'print("  E(total)      = %20.10f Hartree" % e, flush=True)\n'
        f'print("FINAL ENERGY (Hartree):", e, flush=True)\n'

    )


def extract_archive(archive: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    name = archive.name
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    elif name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(dest, filter="data")
    else:
        raise ValueError(f"Unsupported archive: {archive}")
    subdirs = [d for d in dest.iterdir() if d.is_dir()]
    if len(subdirs) == 1 and not list(dest.glob("*.xyz")):
        return subdirs[0]
    return dest


def discover_user_jobs(
    user_xyz: Path, stage_root: Path, dataset_name: str, basis_preset: str,
    restart_source: InputCheckpointSource | None = None,
    require_restart: bool = False,
    optional_restart_sources=None,
) -> list[Job]:
    basis_tag = re.sub(r"[^a-z0-9]+", "-", basis_preset).strip("-")
    user_stage = stage_root / f"{dataset_name}_{basis_tag}_inputfile"
    if user_xyz.is_dir():
        xyz_dir = user_xyz
    else:
        xyz_dir = extract_archive(user_xyz, stage_root / f"_user_extract_{dataset_name}")

    xyz_files = sorted(xyz_dir.glob("*.xyz"))
    for xyz in xyz_files:
        _, _, atom_block, _ = parse_xyz(xyz)
        try:
            load_basis_preset(atom_block, basis_preset)
        except Exception as exc:
            raise ValueError(f"{xyz.name}: {exc}") from exc

    jobs: list[Job] = []
    for xyz in xyz_files:
        name = xyz.stem
        initial_chk = None
        if require_restart:
            if restart_source is None:
                raise ValueError(f"no Input checkpoint source selected for {name}")
            initial_chk = _checkpoint_for_molecule(restart_source.root, name)
            validate_input_checkpoint(xyz, initial_chk, basis_preset)
        elif optional_restart_sources is not None:
            initial_chk = matching_test_checkpoint(xyz, basis_preset, optional_restart_sources)
        script_text = generate_user_script(xyz, basis_preset)
        user_stage.mkdir(parents=True, exist_ok=True)
        stage_py = user_stage / f"{name}.py"
        stage_py.write_text(script_text)

        _, _, _, natom = parse_xyz(xyz)
        jobs.append(Job(
            source_py=xyz,
            source_chk=xyz,
            dataset_dir=user_stage.name,
            dataset=dataset_name,
            name=name,
            stage_dir=user_stage,
            stage_py=stage_py,
            stage_chk=user_stage / f"{name}.chk",
            stage_out=user_stage / f"{name}.out",
            natom=natom,
            initial_chk=initial_chk, nao=basis_size(xyz, basis_preset), basis=basis_preset,
        ))
    return jobs


def run_user_job(job: Job, grid: int, srp_path: str, threads: int,
                 python: str) -> tuple[int, float | None, float]:
    env = molecule_environment(threads)
    nthreads = str(threads)
    env.update({
        "AME_NUM_THREADS": nthreads,
        "OMP_NUM_THREADS": nthreads,
        "MKL_NUM_THREADS": nthreads,
        "OPENBLAS_NUM_THREADS": nthreads,
        "NUMEXPR_NUM_THREADS": nthreads,
        "HDF5_USE_FILE_LOCKING": "FALSE",
        "AME_GRID_LEVEL": str(grid),
        "AME_SRP_FUNCTIONAL": srp_path,
        "AME_CHKFILE": str(job.stage_chk),
        "PYTHONPATH": str(Path(__file__).resolve().parent) + os.pathsep + env.get("PYTHONPATH", ""),
    })
    if job.initial_chk is not None:
        env["DFTHUB_INITIAL_CHKFILE"] = str(job.initial_chk)
    env["DFTHUB_SCF_IDENTITY"] = job_identity(job.source_py, job.basis, srp_path, grid)
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [python, job.stage_py.name]
    t0 = time.time()
    with job.stage_out.open("w") as fh:
        rc = subprocess.run(cmd, cwd=job.stage_dir, env=env,
                            stdout=fh, stderr=subprocess.STDOUT).returncode
    dt = time.time() - t0
    return rc, parse_energy(job.stage_out), dt


def _occupied_coefficients(mo_coeff, mo_occ):
    """Return occupied orbital coefficient matrices, one per spin channel."""
    import numpy as np

    coeff = np.asarray(mo_coeff)
    occ = np.asarray(mo_occ)
    if coeff.ndim == 2:
        return [coeff[:, occ > 0.5]]
    if coeff.ndim == 3 and occ.ndim == 2 and coeff.shape[0] == occ.shape[0]:
        return [coeff[index][:, occ[index] > 0.5] for index in range(coeff.shape[0])]
    raise ValueError("unsupported checkpoint orbital/occupation shape")


def _occupied_determinant_overlap(reference_coeff, current_coeff, overlap_matrix):
    """Absolute determinant overlap for one occupied spin channel."""
    import numpy as np

    if reference_coeff.shape[1] != current_coeff.shape[1]:
        raise ValueError("reference and SCF occupied orbital counts differ")
    matrix = reference_coeff.conj().T @ overlap_matrix @ current_coeff
    sign, log_abs = np.linalg.slogdet(matrix)
    if sign == 0 or not np.isfinite(log_abs):
        return 0.0
    return float(np.clip(np.exp(log_abs), 0.0, 1.0))


def compute_wavefunction_overlap(reference_chk: Path, current_chk: Path) -> dict:
    """Compare occupied SCF orbitals with the initial CF22D checkpoint.

    The reported total is the absolute Slater determinant overlap. Closed-shell
    RKS uses the square of the spatial determinant overlap; UKS multiplies the
    alpha and beta channel overlaps.
    """
    import numpy as np
    from pyscf.scf import chkfile as scf_chkfile

    reference_mol, reference_record = scf_chkfile.load_scf(str(reference_chk))
    current_mol, current_record = scf_chkfile.load_scf(str(current_chk))
    if not gto_same_molecule(reference_mol, current_mol):
        raise ValueError("reference and SCF checkpoints describe different molecules or bases")
    overlap_matrix = current_mol.intor("int1e_ovlp")
    reference_channels = _occupied_coefficients(reference_record["mo_coeff"], reference_record["mo_occ"])
    current_channels = _occupied_coefficients(current_record["mo_coeff"], current_record["mo_occ"])
    if len(reference_channels) != len(current_channels):
        raise ValueError("reference and SCF spin channel counts differ")
    channel_values = [
        _occupied_determinant_overlap(reference, current, overlap_matrix)
        for reference, current in zip(reference_channels, current_channels)
    ]
    total = channel_values[0] ** 2 if len(channel_values) == 1 else float(np.prod(channel_values))
    return {
        "metric": "occupied_slater_determinant_overlap",
        "reference": "Initial CF22D density checkpoint",
        "overlap": float(np.clip(total, 0.0, 1.0)),
        "alpha": channel_values[0],
        "beta": channel_values[1] if len(channel_values) > 1 else channel_values[0],
    }


def _latest_input_checkpoint_snapshot(output_dir: Path) -> Path:
    """Find the newest completed Input checkpoint tree, including legacy trees."""
    root = output_dir / "input_srp"
    candidates = []
    for manifest in root.glob("*/manifest.json") if root.is_dir() else []:
        try:
            data = json.loads(manifest.read_text())
        except (OSError, ValueError):
            continue
        if data.get("complete") is True:
            candidates.append((float(data.get("created_at", manifest.stat().st_mtime)), manifest.parent))
    if not candidates and root.is_dir():
        candidates = [(entry.stat().st_mtime, entry) for entry in root.iterdir() if entry.is_dir() and any(entry.rglob("*.chk"))]
    if not candidates:
        raise FileNotFoundError(f"no completed Input checkpoint tree exists below {root}")
    return max(candidates, key=lambda item: item[0])[1]


def _overlap_reference_root(output_dir: Path, target_snapshot: Path) -> Path:
    return _output_root(output_dir) / "weight_0" / "work"


def run_overlap_only(output_dir: Path) -> None:
    """Calculate overlap from existing Input checkpoints without running SCF."""
    output_dir = Path(output_dir).resolve()
    target_snapshot = _latest_input_checkpoint_snapshot(output_dir)
    reference_root = _overlap_reference_root(output_dir, target_snapshot)
    target_checkpoints = sorted(target_snapshot.rglob("*.chk"))
    if not target_checkpoints:
        raise FileNotFoundError(f"no Input result checkpoints found below {target_snapshot}")
    rows = []
    for target in target_checkpoints:
        molecule = target.stem
        row = {"molecule": molecule}
        try:
            reference = _checkpoint_for_molecule(reference_root, molecule)
            row.update({"status": "available", **compute_wavefunction_overlap(reference, target)})
        except Exception as exc:
            row.update({"status": "unavailable", "overlap": None, "reason": str(exc)})
        rows.append(row)
        print(f"  overlap {molecule}: {row.get('overlap', 'unavailable')}", flush=True)
    available = [row for row in rows if row.get("status") == "available" and row.get("overlap") is not None]
    report = {
        "metric": "occupied_slater_determinant_overlap",
        "reference": "Initial CF22D density checkpoint",
        "rows": rows,
        "available": len(available),
        "total": len(rows),
        "mean": sum(row["overlap"] for row in available) / len(available) if available else None,
    }
    result_path = output_dir / "SinglePointResults.input.json"
    try:
        payload = json.loads(result_path.read_text()) if result_path.is_file() else {"scope": "input", "complete": True}
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot update Input result file: {exc}") from exc
    payload["wavefunction_overlap"] = report
    temporary = result_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    temporary.replace(result_path)
    overlap_result = output_dir / "SinglePointResults.overlap.json"
    overlap_result.write_text(json.dumps({"scope": "overlap", "complete": len(available) == len(rows), **report}, indent=2, ensure_ascii=False))
    if len(available) != len(rows):
        raise RuntimeError(f"overlap unavailable for {len(rows) - len(available)} of {len(rows)} molecules")


def gto_same_molecule(reference_mol, current_mol) -> bool:
    """Compare molecule metadata without importing PySCF at module import time."""
    from pyscf import gto

    return (
        reference_mol.charge == current_mol.charge
        and reference_mol.spin == current_mol.spin
        and reference_mol.nelectron == current_mol.nelectron
        and reference_mol.nao_nr() == current_mol.nao_nr()
        and gto.mole.same_mol(reference_mol, current_mol, cmp_basis=True)
    )


def compute_user_errors(
    energy_map: dict[str, float], ref_path: Path, dataset_name: str,
    start_index: int = 0,
):
    errors: list[float] = []
    rows: list[dict] = []
    idx = start_index
    with ref_path.open() as f:
        for line in f:
            parsed = parse_ref_line(line)
            if parsed is None:
                continue
            coeffs, names, ref, ratioo, has_ratioo = parsed
            missing = [n for n in names if n not in energy_map]
            if missing:
                continue
            pred_h = sum(c * energy_map[n] for c, n in zip(coeffs, names))
            calc = pred_h * HARTREE_TO_KCAL / ratioo
            ref_scaled = ref * has_ratioo / ratioo
            error = calc - ref_scaled
            errors.append(error)
            idx += 1
            label = "+".join(f"{c:g}*{n}" for c, n in zip(coeffs, names))
            rows.append({
                "index": idx,
                "system": f"{dataset_name}: {label}",
                "reference": round(ref_scaled, 4),
                "calculated": round(calc, 4),
                "unbiasedError": round(abs(error), 4),
            })
    mae = sum(abs(e) for e in errors) / len(errors) if errors else 0.0
    return rows, round(mae, 4), len(errors)


# ---------------------------------------------------------------------------
# Error analysis (from ame418_error_analysis.py)
# ---------------------------------------------------------------------------

def parse_ref_line(line: str):
    parts = line.split()
    if not parts:
        return None
    n_col = len(parts)
    if n_col < 3:
        return None
    if n_col % 2 == 0:
        coeffs = [float(parts[i]) for i in range(0, n_col - 2, 2)]
        names = [parts[i] for i in range(1, n_col - 1, 2)]
        ref = float(parts[n_col - 2])
        ratioo = float(parts[n_col - 1])
        has_ratioo = 1.0
    else:
        coeffs = [float(parts[i]) for i in range(0, n_col - 1, 2)]
        names = [parts[i] for i in range(1, n_col - 1, 2)]
        ref = float(parts[n_col - 1])
        ratioo = 1.0
        has_ratioo = HARTREE_TO_KCAL
    return coeffs, names, ref, ratioo, has_ratioo


def compute_errors(results_by_dataset: dict[str, dict[str, float]]):
    """Compute per-dataset MAE and per-reaction errors against Database2 refs."""
    summary_rows = []
    all_target_rows = []
    global_idx = 0

    for dataset, spec in sorted(DATASET_SPECS.items()):
        energy_map: dict[str, float] = {}
        for ds in spec["energy_datasets"]:
            for name, energy in results_by_dataset.get(ds, {}).items():
                if name not in energy_map:
                    energy_map[name] = energy
        aliases = spec.get("aliases", {})
        for alias, target in aliases.items():
            if alias not in energy_map and target in energy_map:
                energy_map[alias] = energy_map[target]

        errors: list[float] = []
        rows: list[dict] = []
        for ref_name in spec["refs"]:
            ref_path = REF_ROOT / ref_name
            if not ref_path.exists():
                continue
            with ref_path.open() as f:
                for line in f:
                    parsed = parse_ref_line(line)
                    if parsed is None:
                        continue
                    coeffs, names, ref, ratioo, has_ratioo = parsed
                    missing = [n for n in names if n not in energy_map]
                    if missing:
                        continue
                    pred_h = sum(c * energy_map[n] for c, n in zip(coeffs, names))
                    calc = pred_h * HARTREE_TO_KCAL / ratioo
                    ref_scaled = ref * has_ratioo / ratioo
                    error = calc - ref_scaled
                    errors.append(error)
                    global_idx += 1
                    label = "+".join(f"{c:g}*{n}" for c, n in zip(coeffs, names))
                    rows.append({
                        "index": global_idx,
                        "system": f"{dataset}: {label}",
                        "reference": round(ref_scaled, 4),
                        "calculated": round(calc, 4),
                        "unbiasedError": round(abs(error), 4),
                    })

        if errors:
            mae = sum(abs(e) for e in errors) / len(errors)
            summary_rows.append({"name": dataset, "mue": round(mae, 4)})
            all_target_rows.extend(rows)

    overall_mue = 0.0
    if all_target_rows:
        overall_mue = sum(r["unbiasedError"] for r in all_target_rows) / len(all_target_rows)

    return all_target_rows, round(overall_mue, 4), summary_rows


def input_completion(user_jobs, test_jobs, energies, user_rows, test_rows,
                     user_reference, test_reference):
    """Training readiness is independent of optional test-set evaluation."""
    def coverage(jobs, rows, reference):
        with reference.open() as handle:
            expected = sum(parse_ref_line(line) is not None for line in handle)
        missing = sorted(job.name for job in jobs if job not in energies)
        counts = {
            "completedMolecules": len(jobs) - len(missing), "totalMolecules": len(jobs),
            "completedReactions": len(rows or []), "totalReactions": expected,
            "failedMolecules": missing,
        }
        complete = bool(jobs) and not missing and expected > 0 and len(rows or []) == expected
        return complete, counts

    training_complete, training_coverage = coverage(user_jobs, user_rows, user_reference)
    test_complete, test_coverage = (coverage(test_jobs, test_rows, test_reference)
                                    if test_reference else (None, None))
    return {
        "trainingComplete": training_complete, "testComplete": test_complete,
        "evaluationComplete": training_complete and test_complete is not False,
        "trainingCoverage": training_coverage, "testCoverage": test_coverage,
    }


def write_spe_json(output_dir: Path, target_rows, target_mue, summary_rows,
                   user_rows=None, user_mue=None, user_dataset_name=None,
                   test_rows=None, test_mue=None, test_dataset_name=None,
                   scope="ame418", complete=True, grid_level=None, descriptor_snapshot_id=None,
                   molecular_energies=None, corrections_sha256=None,
                   initial_guess_source=None, wavefunction_overlap=None, completion=None):
    payload = {
        "scope": scope,
        "complete": complete,
        "grid_level": grid_level,
        "descriptor_snapshot_id": descriptor_snapshot_id,
        "targetDatabaseTitle": "AME418 Self-consistent Results (SRP)",
        "targetRows": target_rows,
        "targetMue": target_mue,
        "summaryTitle": "MAE by Sub-database (kcal/mol)",
        "summaryRows": summary_rows,
    }
    if completion is not None:
        payload.update(completion)
    if initial_guess_source is not None:
        payload["initial_guess_source"] = initial_guess_source
    if wavefunction_overlap is not None:
        payload["wavefunction_overlap"] = wavefunction_overlap
    if user_rows is not None:
        payload["userDatasetTitle"] = f"{user_dataset_name} Single Point Energy Results (SRP)"
        payload["userTargetRows"] = user_rows
        payload["userTargetMue"] = user_mue
        payload["summaryRows"] = summary_rows + [
            {"name": user_dataset_name, "mue": user_mue}
        ]
    if test_dataset_name is not None:
        payload["testDatasetTitle"] = f"{test_dataset_name} Test Set Self-consistent Results (SRP)"
        payload["testTargetRows"] = test_rows or []
        payload["testTargetMue"] = test_mue
        payload["testDatasetName"] = test_dataset_name
        payload["testSetExcludedFromOptimization"] = True
    if scope == "input":
        payload["targetDatabaseTitle"] = f"{user_dataset_name} Self-consistent Results (SRP)"
        payload["targetRows"] = user_rows or []
        payload["targetMue"] = user_mue
        if molecular_energies is not None:
            payload["energy_convention"] = "electronic + stored D3 + stored energy shift"
            payload["correction_source"] = "Input columns 60/61, inherited unchanged from the initial fit"
            payload["corrections_sha256"] = corrections_sha256
            payload["molecular_energies"] = molecular_energies
    out = output_dir / f"SinglePointResults.{scope}.json"
    temporary = out.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    temporary.replace(out)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cf22d-optimized",
                    help="Path to CF22D_optimized.py with the SRP functional")
    ap.add_argument("--output", required=True,
                    help="Output directory (weight_N/) for scope-specific result JSON")
    ap.add_argument("--scope", choices=("input", "ame418"), default="input",
                    help="Calculate only Input (default) or only AME418")
    ap.add_argument("--grid", type=int, default=None,
                    help="PySCF mf.grids.level (default: Input 6, AME418 5)")
    ap.add_argument("--cores", type=int, default=TASK_THREADS, help="task thread budget (capped by configured capacity)")
    ap.add_argument("--max-threads", type=int, default=16,
                    help="max threads per job (actual count based on basis size)")
    ap.add_argument("--python", default=sys.executable, help="Python executable")
    ap.add_argument("--force", action="store_true", help="rerun AME418 jobs; legacy no-op for Input retries")
    ap.add_argument("--fresh", action="store_true", help="start a fresh Input snapshot instead of resuming")
    ap.add_argument("--overlap-only", action="store_true",
                    help="calculate overlap from existing Input checkpoints without running SCF")
    ap.add_argument("--no-pin", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--user-xyz",
                    help="User dataset: archive (.zip/.tgz) or directory of .xyz files")
    ap.add_argument("--user-ref",
                    help="User dataset: reference file (same format as AME418 refs)")
    ap.add_argument("--test-xyz",
                    help="Optional evaluation-only test geometry archive or directory")
    ap.add_argument("--test-ref",
                    help="Optional evaluation-only test reference file")
    ap.add_argument("--user-basis", choices=SUPPORTED_BASIS, default=DEFAULT_BASIS,
                    help=f"Basis/ECP preset for the user dataset only (default: {DEFAULT_BASIS})")
    args = ap.parse_args()
    if args.scope == "input":
        if args.force:
            print("Input retries resume verified checkpoints; use --fresh to recompute.", flush=True)
        args.force = args.fresh
    if args.grid is None:
        args.grid = 6 if args.scope == "input" else 5
    if args.scope == "input" and not args.overlap_only and not (args.user_xyz and args.user_ref):
        ap.error("Input scope requires --user-xyz and --user-ref")
    if bool(args.test_xyz) != bool(args.test_ref):
        ap.error("Test scope requires both --test-xyz and --test-ref")
    if args.scope == "ame418" and (args.user_xyz or args.user_ref):
        ap.error("AME418 scope does not accept user dataset arguments")
    if args.overlap_only and args.scope != "input":
        ap.error("--overlap-only is only valid with --scope input")
    if not args.overlap_only and not args.cf22d_optimized:
        ap.error("--cf22d-optimized is required unless --overlap-only is used")
    if args.cores < 1 or args.max_threads < 1:
        ap.error("Core and thread budgets must be positive")
    args.cores = min(args.cores, TASK_THREADS)
    args.max_threads = min(args.max_threads, 16)
    if __name__ == '__main__':
        enter_task(args.output, args.cores)

    srp_path = Path(args.cf22d_optimized).resolve() if args.cf22d_optimized else None
    output_dir = Path(args.output).resolve()
    stage_root = output_dir / ("input_srp" if args.scope == "input" else "ame418_srp")

    if args.overlap_only:
        print(f"INPUT wavefunction overlap-only calculation", flush=True)
        print(f"  Output: {output_dir}", flush=True)
        run_overlap_only(output_dir)
        print("SUCCESS!", flush=True)
        return

    if not srp_path.exists():
        print(f"[Error] CF22D_optimized.py not found: {srp_path}", flush=True)
        sys.exit(1)

    print(f"{args.scope.upper()} SRP self-consistent single-point energy calculation", flush=True)
    print(f"  SRP functional: {srp_path}", flush=True)
    print(f"  Output: {output_dir}", flush=True)
    if args.scope == "ame418":
        print(f"  AME418 root: {AME418_ROOT}", flush=True)
        print(f"  Ref root: {REF_ROOT}", flush=True)

    # Discover user dataset jobs
    user_jobs: list[Job] = []
    user_ref_path: Path | None = None
    user_dataset_name: str | None = None
    test_jobs: list[Job] = []
    test_ref_path: Path | None = None
    test_dataset_name: str | None = None
    input_checkpoint_source: InputCheckpointSource | None = None
    if args.scope == "input":
        user_xyz_path = Path(args.user_xyz).resolve()
        user_ref_path = Path(args.user_ref).resolve()
        if user_xyz_path.is_dir():
            user_dataset_name = user_xyz_path.name
        else:
            stem = user_xyz_path.name
            for sfx in (".zip", ".tar.gz", ".tgz"):
                if stem.endswith(sfx):
                    stem = stem[: -len(sfx)]
                    break
            user_dataset_name = stem
        stage_root, snapshot_metadata = prepare_input_snapshot(
            output_dir, user_xyz_path, user_ref_path, srp_path, args.user_basis, args.grid,
            test_geometry=Path(args.test_xyz).resolve() if args.test_xyz else None,
            test_reference=Path(args.test_ref).resolve() if args.test_ref else None,
            force=args.fresh,
        )
        user_xyz_path = stage_root / "input" / user_xyz_path.name
        user_ref_path = stage_root / "input/INPUT_ref"
        srp_path = stage_root / "CF22D_optimized.py"
        print(f"  User dataset: {user_dataset_name}", flush=True)
        print(f"  User xyz: {user_xyz_path}", flush=True)
        print(f"  User ref: {user_ref_path}", flush=True)
        print(f"  User basis: {args.user_basis}", flush=True)
        try:
            input_checkpoint_source = resolve_input_checkpoint_source(output_dir, snapshot_metadata)
            source_metadata = {
                "mode": input_checkpoint_source.kind,
                "snapshot_id": input_checkpoint_source.snapshot_id,
                "parent_run": input_checkpoint_source.parent_run,
            }
            snapshot_metadata["initial_guess_source"] = source_metadata
            write_json(stage_root / "manifest.json", snapshot_metadata)
            source_label = input_checkpoint_source.kind
            if input_checkpoint_source.snapshot_id:
                source_label += f" snapshot={input_checkpoint_source.snapshot_id}"
            print(f"  Input initial density source: {source_label}", flush=True)
            user_jobs = discover_user_jobs(
                user_xyz_path, stage_root, user_dataset_name, args.user_basis,
                restart_source=input_checkpoint_source, require_restart=True,
            )
        except Exception as exc:
            print(f"[Error] Input checkpoint preflight failed: {exc}", flush=True)
            sys.exit(1)
        print(f"  User molecules: {len(user_jobs)}", flush=True)
        if args.test_xyz and args.test_ref:
            test_xyz_path = stage_root / "input/test_set" / Path(args.test_xyz).name
            test_ref_path = stage_root / "input/test_set" / Path(args.test_ref).name
            stem = test_xyz_path.name
            for suffix in (".zip", ".tar.gz", ".tgz"):
                if stem.endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            test_dataset_name = stem.removeprefix("test_") or "test"
            test_stage = stage_root / "test_srp"
            test_jobs = discover_user_jobs(
                test_xyz_path, test_stage, test_dataset_name, args.user_basis,
                optional_restart_sources=test_checkpoint_sources(output_dir, input_checkpoint_source),
            )
            snapshot_metadata['test_initial_guess_checkpoints'] = {
                job.name: str(job.initial_chk) if job.initial_chk else None for job in test_jobs
            }
            write_json(stage_root / 'manifest.json', snapshot_metadata)
            print(f"  Test dataset: {test_dataset_name} ({len(test_jobs)} molecules; excluded from optimization)", flush=True)

    # Discover AME418 jobs
    all_jobs, skipped = discover(stage_root) if args.scope == "ame418" else ([], [])
    combined_jobs = all_jobs + user_jobs + test_jobs
    if not combined_jobs:
        print(f"[Error] No molecules found for {args.scope}", flush=True)
        sys.exit(1)
    jobs = combined_jobs
    failed_jobs: set[Job] = set()
    energies_by_job = {}
    wavefunction_rows: list[dict] = []
    overlap_reference_root = (_output_root(output_dir) / "weight_0" / "work") if args.scope == "input" else None
    if not args.force:
        for job in combined_jobs:
            energy = (parse_energy(job.stage_out) if args.scope == 'ame418' else
                      reusable_user_energy(job, args.grid, srp_path))
            if energy is not None:
                energies_by_job[job] = energy
        jobs = [job for job in combined_jobs if job not in energies_by_job]

    if not jobs and not args.force:
        print(f"All {len(combined_jobs)} jobs already completed, running error analysis...",
              flush=True)
    elif not jobs:
        print("No jobs found (no .chk files in AME418?)", flush=True)
        sys.exit(1)
    else:
        total_cores = args.cores
        max_thr = args.max_threads

        # Show thread allocation summary
        thr_counts = {}
        for j in jobs:
            t = job_threads(j, max_thr)
            thr_counts[t] = thr_counts.get(t, 0) + 1
        thr_summary = " ".join(f"{t}thr×{n}" for t, n in sorted(thr_counts.items()))
        print(f"jobs={len(jobs)} skipped_no_chk={len(skipped)} "
              f"core_budget={total_cores} max_threads={max_thr} grid={args.grid}",
              flush=True)
        print(f"  thread allocation by AO basis size: {thr_summary}", flush=True)

        total = len(jobs)
        failed_count = 0
        # Stage shared helper modules before any molecular process imports them.
        if args.scope == 'ame418':
            for job in jobs:
                stage_job(job)

        def run_job(job, threads):
            execute = run_user_job if args.scope == 'input' else run_one
            return execute(job, args.grid, str(srp_path), threads, args.python)

        t0 = time.time()
        for done, (job, result, error) in enumerate(molecular_pool(
                jobs, lambda job: job.natom, run_job, total_cores, max_thr,
                nao=lambda job: job.nao or max(1, job.natom * 20)), 1):
            if error is not None:
                print(f"[Error] {job.name}: {error}", flush=True)
            rc, energy, dt = result if error is None else (-1, None, 0.0)
            nthreads = min(job_threads(job, max_thr), total_cores)
            status = "OK  " if rc == 0 and energy is not None else "FAIL"
            if status == "FAIL":
                failed_count += 1
                failed_jobs.add(job)
            else:
                energies_by_job[job] = energy
            try:
                rel = job.source_py.relative_to(AME418_ROOT)
            except ValueError:
                rel = Path(job.dataset_dir) / job.source_py.name
            e_text = f"{energy:.8f}" if energy is not None else "----"
            print(f"[{done:4d}/{total}] {status} {rel!s:46s} "
                  f"E={e_text} ({dt:.0f}s) [natom={job.natom},nao={job.nao},thr={nthreads},"
                  f"memory_mb={molecule_environment(nthreads)['DFTHUB_MAXMEM']}]", flush=True)
        elapsed = time.time() - t0
        ok_count = total - failed_count
        print(f"\nComputation done: {ok_count}/{total} succeeded in {elapsed:.0f}s",
              flush=True)

    if args.scope == "input":
        for job in combined_jobs:
            if job not in energies_by_job:
                continue
            row = {"molecule": job.name}
            reference_root = overlap_reference_root if job in user_jobs else _output_root(output_dir) / "weight_0/test_work"
            try:
                reference_chk = _checkpoint_for_molecule(reference_root, job.name)
                row.update({"status": "available", **compute_wavefunction_overlap(reference_chk, job.stage_chk)})
            except Exception as exc:
                row.update({"status": "unavailable", "overlap": None, "reason": str(exc)})
            wavefunction_rows.append(row)

    # Collect training and test energies, including verified reused molecules.
    print("Collecting energies from staged outputs...", flush=True)
    results_by_dataset: dict[str, dict[str, float]] = {}
    for job in all_jobs + user_jobs:
        energy = energies_by_job.get(job)
        if energy is not None:
            results_by_dataset.setdefault(job.dataset, {})[job.name] = energy

    total_energies = len(energies_by_job)
    print(f"Collected {total_energies} energies across "
          f"{len(results_by_dataset)} datasets", flush=True)

    input_energies = molecular_energies = corrections_sha256 = None
    if args.scope == "input":
        input_energies, molecular_energies, corrections_sha256 = correct_input_energies(
            results_by_dataset.get(user_dataset_name, {}), stage_root / "source-INPUT",
        )
        snapshot_metadata["corrections_sha256"] = corrections_sha256
        print("Input results include the initial fit's stored D3 dispersion and energy shifts; no D3 recalculation.", flush=True)

    # Write results.tsv for reference
    tsv_path = stage_root / "results.tsv"
    stage_root.mkdir(parents=True, exist_ok=True)
    with tsv_path.open("w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["dataset", "name", "electronic_energy_hartree" if args.scope == "input" else "energy_hartree", "status"] +
                   (["d3_hartree", "energy_shift_kcal_mol", "total_energy_hartree"] if args.scope == "input" else []))
        for job in sorted(all_jobs + user_jobs, key=lambda j: (j.dataset, j.name)):
            energy = energies_by_job.get(job)
            status = "ok" if energy is not None else "fail"
            fields = [job.dataset, job.name, f"{energy:.12f}" if energy is not None else "", status]
            if args.scope == "input":
                detail = molecular_energies.get(job.name, {})
                fields += [detail.get(key, "") for key in ("d3_hartree", "energy_shift_kcal_mol", "total_hartree")]
            w.writerow(fields)

    # Error analysis — AME418
    target_rows, target_mue, summary_rows = [], None, []
    if args.scope == "ame418":
        print("Running error analysis against Database2 references...", flush=True)
        target_rows, target_mue, summary_rows = compute_errors(results_by_dataset)

    if args.scope == "ame418" and not summary_rows:
        print("[Error] No error analysis results — missing reference data or energies",
              flush=True)
        sys.exit(1)

    # Error analysis — user dataset
    user_target_rows = None
    user_target_mue = None
    test_target_rows = None
    test_target_mue = None
    if user_ref_path and user_dataset_name:
        user_energy_map = input_energies
        if user_energy_map:
            start_idx = max((r["index"] for r in target_rows), default=0)
            user_target_rows, user_target_mue, n_user = compute_user_errors(
                user_energy_map, user_ref_path, user_dataset_name, start_idx,
            )
            print(f"\nUser dataset '{user_dataset_name}': {n_user} reactions, "
                  f"MAE = {user_target_mue} kcal/mol", flush=True)
        else:
            print(f"\n[Warn] No energies collected for user dataset '{user_dataset_name}'",
                  flush=True)
    if test_ref_path and test_dataset_name:
        test_raw = {job.name: energies_by_job[job] for job in test_jobs if job in energies_by_job}
        test_energies, _, _ = correct_input_energies(test_raw, stage_root / "source-TEST_INPUT") if (stage_root / "source-TEST_INPUT").is_file() else (test_raw, {}, None)
        if test_energies:
            test_target_rows, test_target_mue, n_test = compute_user_errors(test_energies, test_ref_path, test_dataset_name)
            print(f"\nTest dataset '{test_dataset_name}': {n_test} reactions, MAE = {test_target_mue} kcal/mol", flush=True)

    completion = None
    complete = total_energies == len(combined_jobs) and not skipped
    if args.scope == "input":
        completion = input_completion(user_jobs, test_jobs, energies_by_job,
                                      user_target_rows, test_target_rows, user_ref_path, test_ref_path)
        # Input completion gates refinement. The optional test set never supplies
        # optimization descriptors and has its own completion flag.
        complete = completion["trainingComplete"]

    descriptor_snapshot_id = None
    if args.scope == "input" and complete:
        descriptor_snapshot_id = publish_input_snapshot(output_dir, stage_root, snapshot_metadata, user_jobs)

    out_json = write_spe_json(
        output_dir, target_rows, target_mue, summary_rows,
        user_rows=user_target_rows, user_mue=user_target_mue,
        user_dataset_name=user_dataset_name,
        test_rows=test_target_rows, test_mue=test_target_mue,
        test_dataset_name=test_dataset_name,
        scope=args.scope, complete=complete, grid_level=args.grid,
        descriptor_snapshot_id=descriptor_snapshot_id,
        completion=completion,
        molecular_energies=molecular_energies, corrections_sha256=corrections_sha256,
        initial_guess_source=(snapshot_metadata.get("initial_guess_source")
                              if args.scope == "input" else None),
        wavefunction_overlap=(
            {
                "metric": "occupied_slater_determinant_overlap",
                "reference": "Initial CF22D density checkpoint",
                "rows": wavefunction_rows,
                "available": sum(1 for row in wavefunction_rows if row.get("status") == "available"),
                "total": len(wavefunction_rows),
                "mean": (
                    sum(row["overlap"] for row in wavefunction_rows if row.get("status") == "available") /
                    sum(1 for row in wavefunction_rows if row.get("status") == "available")
                    if any(row.get("status") == "available" for row in wavefunction_rows) else None
                ),
            }
            if args.scope == "input" and (wavefunction_rows or args.force) else None
        ),
    )
    print(f"\nResults written to {out_json}", flush=True)
    if args.scope == "ame418":
        print(f"AME418 MAE: {target_mue} kcal/mol", flush=True)
    print(f"Sub-databases evaluated: {len(summary_rows)}", flush=True)
    for row in summary_rows:
        print(f"  {row['name']:25s} MAE = {row['mue']:.4f} kcal/mol", flush=True)
    if user_target_mue is not None:
        print(f"  {user_dataset_name:25s} MAE = {user_target_mue:.4f} kcal/mol (user)",
                  flush=True)
    if not complete:
        print("[Error] Some molecules failed; the result file contains partial results only", flush=True)
        sys.exit(1)
    if completion and completion["testComplete"] is False:
        coverage = completion["testCoverage"]
        print(f"[Warn] Optional test set incomplete: {coverage['completedMolecules']}/{coverage['totalMolecules']} molecules, "
              f"{coverage['completedReactions']}/{coverage['totalReactions']} reactions. "
              "Training SCF and descriptors are complete; refinement is available. "
              "Retry Calculate Input to resume unfinished test molecules.", flush=True)


if __name__ == "__main__":
    main()
