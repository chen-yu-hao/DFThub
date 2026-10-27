#!/usr/bin/env bash
set -euo pipefail
bundle_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dfthub_python="${DFTHUB_INSTALL_PYTHON:-python3.12}"
dfthub_venv="${1:-$PWD/.venv-dfthub}"
"$dfthub_python" - "$bundle_dir" <<'PY'
import hashlib, json, platform, sys
from pathlib import Path
root = Path(sys.argv[1])
target = json.loads((root/'platform.json').read_text())
if (platform.system(), platform.machine(), '.'.join(platform.python_version().split('.')[:2])) != (target['system'], target['machine'], '.'.join(target['python'].split('.')[:2])):
    raise SystemExit('Bundle does not match this Python/platform')
for line in (root/'SHA256SUMS').read_text().splitlines():
    expected, name = line.split('  ', 1)
    if hashlib.sha256((root/name).read_bytes()).hexdigest() != expected:
        raise SystemExit('Checksum mismatch: '+name)
PY
"$dfthub_python" -m venv "$dfthub_venv"
"$dfthub_venv/bin/python" -m pip install --no-index --require-hashes --find-links "$bundle_dir/wheelhouse" -r "$bundle_dir/requirements.lock"
"$dfthub_venv/bin/dfthub" doctor --strict
