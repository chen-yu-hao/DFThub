"""Immutable package assets and explicitly configured, writable state."""
import os
import sys
import shutil
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
PROGRAM_DIR = PACKAGE / "pipeline"
RESOURCES = PACKAGE / "resources"


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def load_environment():
    """Load the file named by DFTHUB_ENV_FILE into os.environ.

    This is the only place DFThub reads an environment file; nothing is loaded
    from the source tree implicitly. Variables already present in the process
    environment win, and an empty value (``KEY=``) is ignored, so a blank entry
    behaves exactly like an absent one. Calling it again is harmless.
    """
    name = os.environ.get("DFTHUB_ENV_FILE", "").strip()
    if not name:
        return
    path = Path(name).expanduser()
    if not path.is_file():
        raise ValueError(f"DFTHUB_ENV_FILE={name} does not exist or is not a file")
    if path.stat().st_mode & 0o077:
        raise ValueError(f"{path} must have mode 0600 or 0400 (run: chmod 600 {path})")
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key.replace("_", "").isalnum():
            raise ValueError(f"{path}:{number}: expected KEY=value")
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key, value)


def env_flag(name, default):
    """Read an on/off environment variable; refuse values that are neither."""
    raw = os.environ.get(name, "")
    value = raw.strip().lower()
    if not value:
        return default
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"{name} must be 1 or 0 (got {raw!r})")


def data_dir():
    default = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "dfthub"
    return Path(os.environ.get("DFTHUB_DATA_DIR", str(default))).expanduser().resolve()


def optimizer_dir():
    return Path(os.environ.get("DFTHUB_TMB11_DIR", str(RESOURCES / "optimizer"))).expanduser().resolve()


def input_directory(container):
    """Portable run/snapshot inputs; read historical Linux 'input' directories."""
    container = Path(container)
    portable = container / "inputs"
    if portable.is_dir():
        return portable
    legacy = container / "input"
    return legacy if legacy.is_dir() else portable


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
