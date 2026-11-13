"""Include native-component notices in newly built or cached engine wheels."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

directory = Path(sys.argv[1]).resolve()
notices = Path(__file__).resolve().parent / 'native-licenses'
for wheel in directory.glob('dfthub_pyscf_dft-*.whl'):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(root)
        metadata = next(root.glob('*.dist-info'))
        shutil.copytree(notices, metadata/'licenses/native', dirs_exist_ok=True)
        subprocess.run([sys.executable, '-m', 'wheel', 'pack', str(root), '--dest-dir', str(directory)], check=True)
