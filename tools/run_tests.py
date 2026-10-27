"""Run API modules in separate processes because each owns isolated auth state."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='dfthub-regression-') as temporary:
    env = dict(os.environ, DFTHUB_DATA_DIR=temporary, DFTHUB_MAIL_SUPPRESS='1',
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
               DFTHUB_CPU_THREADS='4', DFTHUB_TASK_THREADS='4', PYTHONDONTWRITEBYTECODE='1')
    for test in sorted((root / 'tests/api').glob('test_*.py')):
        subprocess.run([sys.executable, str(test), '-v'], env=env, check=True)
    for group in ('pipeline', 'packaging'):
        subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(root / 'tests' / group), '-v'], env=env, check=True)
