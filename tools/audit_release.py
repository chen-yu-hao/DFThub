"""Audit publishable paths, production code and all reachable Git history."""
import re
from pathlib import Path
import subprocess
import zipfile

root = Path(__file__).resolve().parents[1]
bad_parts = {'node_modules','__pycache__','.env','auth.db','.jwt_secret','.backups','workflow_user','YuhaoChen'}
patterns = [re.compile(rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'),
            re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'),
            re.compile(rb'https?://[^\s/]+:[^\s/@]+@'),
            re.compile(rb'AKIA[A-Z0-9]{16}')]
errors = []
def check(name, content, runtime=False):
    parts = Path(name).parts
    if any(part in bad_parts for part in parts) or '.bak' in Path(name).name:
        errors.append('Forbidden published path: '+name)
    if runtime and re.search(rb'/home/(?:hpc|cyh|share)/', content):
        errors.append('Host-specific runtime path: '+name)
    if any(p.search(content) for p in patterns):
        errors.append('Credential pattern: '+name)

for wheel in (root/'dist').glob('dfthub-*.whl'):
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            check(name, archive.read(name), runtime=name.endswith('.py'))
tracked = subprocess.check_output(['git','ls-files','-z'], cwd=root).decode().split('\0')
for name in filter(None, tracked):
    p = root/name
    if p.is_file():
        check(name, p.read_bytes(), runtime=name.startswith('src/') and name.endswith('.py'))
# Inspect each historical blob once, without printing its contents.
seen=set()
for line in subprocess.check_output(['git','rev-list','--objects','--all'],cwd=root).decode().splitlines():
    sha, _, name = line.partition(' ')
    if not name or sha in seen:
        continue
    seen.add(sha)
    kind = subprocess.check_output(['git','cat-file','-t',sha],cwd=root).strip()
    if kind == b'blob':
        check('history/'+name, subprocess.check_output(['git','cat-file','blob',sha],cwd=root))
if errors:
    raise SystemExit('\n'.join(errors))
print(f'Release audit passed; {len(seen)} historical objects checked')
