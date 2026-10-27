"""Portable task discovery restricted to this installation and current user."""
from pathlib import Path
import os
import psutil
from .paths import PROGRAM_DIR

SCRIPTS = {"main.py", "opt_demo.py", "run_ame418_srp.py", "run_user_energy.py"}


def tasks():
    for process in psutil.process_iter(["pid", "cmdline", "uids", "status"]):
        try:
            info = process.info
            if info["uids"] is None or info["uids"].real != os.getuid() or info["status"] == psutil.STATUS_ZOMBIE:
                continue
            argv = info["cmdline"] or []
            script = next((Path(arg) for arg in argv[1:3]
                           if Path(arg).name in SCRIPTS and Path(arg).parent.resolve() == PROGRAM_DIR), None)
            if script is None or "--output" not in argv:
                continue
            output = Path(argv[argv.index("--output") + 1])
            if not output.is_absolute():
                output = Path(process.cwd()) / output
            scope = ("energy" if script.name == "run_user_energy.py" else
                     "overlap" if "--overlap-only" in argv else
                     argv[argv.index("--scope") + 1] if "--scope" in argv else
                     "input" if script.name == "run_ame418_srp.py" else "optimization")
            yield {"pid": process.pid, "output": str(output.resolve()), "scope": scope,
                   "mode": "optim" if script.name == "opt_demo.py" else "new"}
        except (psutil.Error, OSError, ValueError, IndexError):
            continue
