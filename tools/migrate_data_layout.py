"""Convert a stopped backup before transferring old Linux data to macOS.

Dry-run is the default. Never run against an active service's data directory.
No result, descriptor or checkpoint file is changed.
"""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data-dir', type=Path, required=True)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
root = args.data_dir.resolve()
candidates = []
for legacy in (root/'Work').glob('*/*/output/**/input'):
    if legacy.is_symlink() or not legacy.is_dir():
        continue
    relative = legacy.relative_to(root).parts
    if legacy.parent.name.startswith(('weight_', 'fork-')) or legacy.parent.parent.name == 'input_srp':
        portable = legacy.with_name('inputs')
        if portable.exists():
            raise SystemExit(f'Both input and inputs exist; resolve before migration: {legacy.parent}')
        candidates.append((legacy, portable))
for legacy, portable in candidates:
    print(f'{legacy} -> {portable}')
if args.apply:
    for legacy, portable in candidates:
        legacy.rename(portable)
print(f'{len(candidates)} directories {"renamed" if args.apply else "would be renamed (dry run)"}')
