"""Retain command output and expose useful failure diagnostics in checks."""
import re
import subprocess
import sys
from pathlib import Path

process = subprocess.Popen(sys.argv[1:], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
lines = []
for line in process.stdout:
    print(line, end='', flush=True)
    lines.append(line.rstrip())
code = process.wait()
Path('ci-command.log').write_text('\n'.join(lines) + '\n')
if code:
    selected = set(range(max(0, len(lines)-30), len(lines)))
    for i, line in enumerate(lines):
        if re.search(r'error:|error |failed|fatal:|not found|no such file|exception|traceback', line, re.I):
            selected.update(range(max(0,i-2), min(len(lines),i+5)))
    message = '\n'.join(lines[i] for i in sorted(selected))[-25000:]
    message = message.replace('%','%25').replace('\r','%0D').replace('\n','%0A')
    print('::error title=Build or test diagnostics::' + message)
raise SystemExit(code)
