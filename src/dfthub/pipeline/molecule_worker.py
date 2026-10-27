"""One isolated initial-SCF/descriptor calculation, launched by the pool."""
import argparse
from pathlib import Path

import main as pipeline

parser = argparse.ArgumentParser()
parser.add_argument('--xyz', required=True)
parser.add_argument('--work-dir', required=True)
parser.add_argument('--basis', required=True)
parser.add_argument('--threads', required=True, type=int)
args = parser.parse_args()
pipeline.BASIS_PRESET = args.basis
pipeline.NUM_THREADS = args.threads
pipeline.LOG_FILE = Path(args.work_dir) / (Path(args.xyz).stem + '.scf.log')
print(f'Molecule {Path(args.xyz).stem}: threads={args.threads}, basis={args.basis}', flush=True)
pipeline.compute_molecule(Path(args.xyz), Path(args.work_dir))
