#!/usr/bin/env bash
set -euo pipefail

bundle_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dfthub_venv="${1:-$PWD/.venv-dfthub}"

expected_py_mm=""
if [[ -f "$bundle_dir/platform.json" ]]; then
  expected_py_mm="$(sed -n 's/.*"python"[[:space:]]*:[[:space:]]*"\([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' "$bundle_dir/platform.json" | head -n 1)"
fi
if [[ -z "$expected_py_mm" && -d "$bundle_dir/wheelhouse" ]]; then
  for whl in "$bundle_dir/wheelhouse"/dfthub_pyscf_dft-*-cp3*-*.whl; do
    if [[ -e "$whl" && "$(basename "$whl")" =~ -cp([0-9])([0-9]+)- ]]; then
      expected_py_mm="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}"
      break
    fi
  done
fi

if [[ -n "${DFTHUB_INSTALL_PYTHON:-}" ]]; then
  dfthub_python="$DFTHUB_INSTALL_PYTHON"
elif [[ -n "$expected_py_mm" ]] && command -v "python${expected_py_mm}" >/dev/null 2>&1; then
  dfthub_python="python${expected_py_mm}"
elif command -v python3 >/dev/null 2>&1; then
  dfthub_python="python3"
elif [[ -n "$expected_py_mm" ]]; then
  dfthub_python="python${expected_py_mm}"
else
  dfthub_python="python3"
fi

if ! command -v "$dfthub_python" >/dev/null 2>&1; then
  if [[ -n "$expected_py_mm" ]]; then
    echo "Error: Python interpreter '$dfthub_python' not found. This bundle requires Python ${expected_py_mm} (install python${expected_py_mm} or set DFTHUB_INSTALL_PYTHON)." >&2
  else
    echo "Error: Python interpreter '$dfthub_python' not found. Install Python 3.10-3.12 or set DFTHUB_INSTALL_PYTHON." >&2
  fi
  exit 1
fi

echo "Selected Python interpreter: $dfthub_python"

"$dfthub_python" - "$bundle_dir" "$expected_py_mm" <<'PY'
import hashlib, json, platform, re, sys
from pathlib import Path

root = Path(sys.argv[1])
expected_mm = sys.argv[2]
actual_mm = f"{sys.version_info.major}.{sys.version_info.minor}"
actual_cp = f"cp{sys.version_info.major}{sys.version_info.minor}"

wheelhouse = root / 'wheelhouse'
wheel_mms = []
if wheelhouse.is_dir():
    for whl in sorted(wheelhouse.glob('dfthub_pyscf_dft-*-cp*-*.whl')):
        m = re.search(r'-cp(\d)(\d+)-', whl.name)
        if m:
            wheel_mms.append(f"{m.group(1)}.{m.group(2)}")

platform_file = root / 'platform.json'
if platform_file.is_file():
    target = json.loads(platform_file.read_text())
    target_mm = '.'.join(target['python'].split('.')[:2])
    if (platform.system(), platform.machine()) != (target['system'], target['machine']):
        raise SystemExit(
            f"Bundle platform mismatch: current platform is {platform.system()} {platform.machine()}, "
            f"but bundle requires {target['system']} {target['machine']}."
        )
    if actual_mm != target_mm:
        raise SystemExit(
            f"Bundle Python version mismatch: interpreter '{sys.executable}' is Python {platform.python_version()} ({actual_cp}), "
            f"but this bundle requires Python {target_mm} (cp{target_mm.replace('.', '')}). "
            f"Install python{target_mm}, set DFTHUB_INSTALL_PYTHON=python{target_mm}, or use the {actual_cp} offline bundle."
        )
elif expected_mm and actual_mm != expected_mm:
    raise SystemExit(
        f"Bundle Python version mismatch: interpreter '{sys.executable}' is Python {platform.python_version()} ({actual_cp}), "
        f"but this bundle requires Python {expected_mm} (cp{expected_mm.replace('.', '')}). "
        f"Install python{expected_mm}, set DFTHUB_INSTALL_PYTHON=python{expected_mm}, or use the {actual_cp} offline bundle."
    )

if wheel_mms and actual_mm not in wheel_mms:
    req = ', '.join(f"Python {v} (cp{v.replace('.', '')})" for v in wheel_mms)
    raise SystemExit(
        f"Wheelhouse Python version mismatch: interpreter '{sys.executable}' is Python {platform.python_version()} ({actual_cp}), "
        f"but wheelhouse requires {req}."
    )

for line in (root / 'SHA256SUMS').read_text().splitlines():
    expected, name = line.split('  ', 1)
    if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
        raise SystemExit('Checksum mismatch: ' + name)
PY
"$dfthub_python" -m venv "$dfthub_venv"
"$dfthub_venv/bin/python" -m pip install --no-index --require-hashes --find-links "$bundle_dir/wheelhouse" -r "$bundle_dir/requirements.lock"
"$dfthub_venv/bin/dfthub" doctor --strict
