"""Copy the locally built frontend; keep pinned Swagger assets in the wheel."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
source = root / 'Client/DFThub/dist-dfthub'
target = root / 'src/dfthub/static'
if not (source / 'index.html').is_file():
    raise SystemExit('Build Client/DFThub first')
target.mkdir(parents=True, exist_ok=True)
for item in target.iterdir():
    if item.name != 'vendor':
        shutil.rmtree(item) if item.is_dir() else item.unlink()
shutil.copytree(source, target, dirs_exist_ok=True)
