"""Single-molecule computation worker for DFThub parallel scheduler.

Called by main.py's CoreScheduler as:
    python compute_worker.py --mode dftd3 --xyz mol.xyz --work-dir /path
    python compute_worker.py --mode scf   --xyz mol.xyz --work-dir /path --threads 8

Results written to disk:
    dftd3: {work_dir}/{name}.d3energy  (text, one float in Eh)
    scf:   {work_dir}/{name}.desc.npy  (numpy array, 78 CF25D values)
"""

import argparse
import os
import sys
from pathlib import Path

from dfthub.paths import pipeline_python
PIPELINE_PYTHON = pipeline_python()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DFThub single-molecule worker")
    parser.add_argument("--mode", required=True, choices=["dftd3", "scf"])
    parser.add_argument("--xyz", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--threads", type=int, default=1)
    args = parser.parse_args()

    if args.mode == "dftd3":
        energy = dftd3_one(args.xyz, args.work_dir)
        print(f"D3 {Path(args.xyz).stem}: {energy:.13E} Eh")
    elif args.mode == "scf":
        ee = scf_one(args.xyz, args.work_dir, args.threads)
        print(f"SCF {Path(args.xyz).stem}: {len(ee)} descriptors, E0={ee[0]:.10f}")
