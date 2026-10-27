"""Immutable package assets and explicitly configured, writable state."""
import os
import sys
import shutil
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
PROGRAM_DIR = PACKAGE / "pipeline"
RESOURCES = PACKAGE / "resources"


def load_environment():
    name = os.environ.get("DFTHUB_ENV_FILE")
    if not name:
        return
    path = Path(name).expanduser()
    if path.stat().st_mode & 0o077:
        raise ValueError("DFTHUB_ENV_FILE must have mode 0600 or 0400")
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip().replace("_", "").isalnum():
            raise ValueError("Invalid environment file entry")
        os.environ.setdefault(key.strip(), value.strip().strip('\"').strip("'"))


def data_dir():
    default = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "dfthub"
    return Path(os.environ.get("DFTHUB_DATA_DIR", str(default))).expanduser().resolve()


def optimizer_dir():
    return Path(os.environ.get("DFTHUB_TMB11_DIR", str(RESOURCES / "optimizer"))).expanduser().resolve()


def pipeline_python():
    value = os.environ.get("DFTHUB_PYTHON", sys.executable)
    resolved = shutil.which(value) or str(Path(value).expanduser())
    if not Path(resolved).is_file():
        raise ValueError("DFTHUB_PYTHON does not name an executable Python")
    return resolved


def initialize_data():
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ("Work", "optimizer", "scheduler"):
        (root / name).mkdir(exist_ok=True, mode=0o700)
    for source in (RESOURCES / "template").rglob("*"):
        if source.is_file():
            target = root / "Work/template" / source.relative_to(RESOURCES / "template")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source, target)
    count = root / "submit_count.txt"
    if not count.exists():
        with count.open("x") as handle:
            handle.write("0\n")
    return root
