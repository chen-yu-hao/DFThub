#!/usr/bin/env python
"""Evaluate a user .tgz with an optimized DFThub functional."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dfthub.pipeline.compute_scheduler import TASK_THREADS, enter_task, molecular_pool
from dfthub.pipeline.run_ame418_srp import discover_user_jobs, run_user_job, parse_energy, reusable_user_energy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cf22d-optimized", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--user-xyz", required=True)
    parser.add_argument("--user-basis", required=True)
    parser.add_argument("--grid", type=int, default=6)
    parser.add_argument("--cores", type=int, default=TASK_THREADS)
    parser.add_argument("--max-threads", type=int, default=16)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    args.cores = min(max(1, args.cores), TASK_THREADS)
    args.max_threads = min(max(1, args.max_threads), 16)
    output = Path(args.output).resolve()
    stage = output / "energy_srp"
    dataset = Path(args.user_xyz).name
    for suffix in (".tar.gz", ".tgz", ".zip"):
        if dataset.endswith(suffix):
            dataset = dataset[: -len(suffix)]
            break
    jobs = discover_user_jobs(Path(args.user_xyz).resolve(), stage, dataset, args.user_basis)
    if not jobs:
        raise SystemExit("No .xyz molecules were found in the uploaded archive")
    enter_task(str(output), args.cores)
    functional = str(Path(args.cf22d_optimized).resolve())
    selected = [job for job in jobs if args.force or reusable_user_energy(job, args.grid, functional) is None]
    if args.force:
        for job in selected:
            job.stage_chk.with_suffix('.progress.json').unlink(missing_ok=True)
    failed = []
    if selected:
        def run(job, threads):
            return run_user_job(job, args.grid, str(Path(args.cf22d_optimized).resolve()), threads, args.python)
        for _done, (job, result, error) in enumerate(
            molecular_pool(selected, lambda job: job.natom, run, args.cores, args.max_threads,
                           nao=lambda job: job.nao or max(1, job.natom * 20)), 1
        ):
            rc, energy, _elapsed = result if error is None else (-1, None, 0.0)
            if rc != 0 or energy is None:
                failed.append({"name": job.name, "error": str(error or "energy calculation failed")})
    energies = []
    for job in jobs:
        value = None if any(item["name"] == job.name for item in failed) else reusable_user_energy(job, args.grid, functional)
        energies.append({"name": job.name, "energy_hartree": value, "status": "ok" if value is not None else "failed"})
    complete = bool(energies) and all(row["status"] == "ok" for row in energies)
    payload = {
        "scope": "energy", "complete": complete, "grid_level": args.grid,
        "userDatasetTitle": f"{dataset} DFT energy results (SRP)", "userDatasetName": dataset,
        "molecularEnergies": energies, "failed": failed, "updated_at": time.time(),
    }
    result_path = output / "SinglePointResults.energy.json"
    temporary = result_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    temporary.replace(result_path)
    print(f"Results written to {result_path}", flush=True)
    if not complete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
