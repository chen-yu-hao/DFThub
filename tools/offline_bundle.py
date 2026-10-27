"""Resolve a wheel-only, hash-locked bundle for the current Python/platform."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from email.parser import Parser

parser = argparse.ArgumentParser()
parser.add_argument('--engine', type=Path, required=True)
parser.add_argument('--package', type=Path, required=True)
parser.add_argument('--output', type=Path, default=Path('dist'))
args = parser.parse_args()
label = f'dfthub-0.1.0-{platform.system().lower()}-{platform.machine()}-cp{sys.version_info.major}{sys.version_info.minor}'
root = args.output.resolve() / label
wheels = root / 'wheelhouse'
wheels.mkdir(parents=True, exist_ok=False)
subprocess.run([sys.executable, '-m', 'pip', 'download', '--only-binary=:all:', '-d', str(wheels),
                str(args.engine.resolve()), str(args.package.resolve())], check=True)
lock = []
for path in sorted(wheels.glob('*.whl')):
    with zipfile.ZipFile(path) as archive:
        metadata = Parser().parsestr(archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))).decode())
    if metadata['Name'].lower() == 'pyscf':
        raise SystemExit('Upstream PySCF must not enter the offline bundle')
    lock.append(f"{metadata['Name']}=={metadata['Version']} --hash=sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}")
(root / 'requirements.lock').write_text('\n'.join(lock) + '\n')
repo = Path(__file__).resolve().parents[1]
shutil.copytree(repo / 'deploy', root / 'deploy')
shutil.copy2(repo / 'README.md', root / 'README.md')
(root / 'platform.json').write_text(json.dumps({'python':platform.python_version(), 'system':platform.system(), 'machine':platform.machine()},indent=2)+'\n')
sums = [f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root)}' for p in sorted(root.rglob('*')) if p.is_file()]
(root / 'SHA256SUMS').write_text('\n'.join(sums)+'\n')
with tarfile.open(args.output / (label + '.tar.gz'), 'w:gz') as archive:
    archive.add(root, arcname=label)
print(root)
