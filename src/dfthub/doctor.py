"""Check actual imported code and native libraries, not just a version string."""
import hashlib
import importlib.metadata as md
import json
import os
from pathlib import Path
import subprocess
import sys
from .paths import PACKAGE, pipeline_python

COMMIT = "72e5b26c91964acbf3186c5348f77a0f7faf44dd"
ENGINE_VERSION = "2.14.0+dfthub.72e5b26c"


def engine_check():
    errors = []
    info = {}
    try:
        import pyscf
        from pyscf.dft import libxc
        from pyscf import gto
        package = Path(pyscf.__file__).resolve().parent
        dist = md.distribution("dfthub-pyscf-dft")
        manifest = json.loads((package / "dfthub-provenance.json").read_text())
        if dist.version != ENGINE_VERSION or manifest["commit"] != COMMIT or manifest["branch"] != "DFT":
            errors.append("The installed engine is not the pinned PySCF DFT build")
        if Path(dist.locate_file("pyscf/__init__.py")).resolve() != package / "__init__.py":
            errors.append("The imported pyscf is outside the DFT distribution")
        try:
            md.distribution("pyscf")
            errors.append("Conflicting upstream pyscf distribution installed; use a clean virtual environment")
        except md.PackageNotFoundError:
            pass
        for name, expected in manifest["files"].items():
            path = package.parent / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                errors.append("Engine file mismatch: " + name)
        if libxc.libxc_version() != "7.1.2":
            errors.append("LibXC 7.1.2 is required")
        libxc.parse_xc("CF22D,CF22D")
        gto.M(atom="H 0 0 0; H 0 0 .74", basis="sto-3g", verbose=0).intor("int1e_ovlp")
        from dftd3.interface import DispersionModel, ZeroDampingParam
        from xclib.CFXXD import CF22D_nxc, CF22D_nxc_rks
        info = {"branch": manifest["branch"], "commit": manifest["commit"],
                "pyscf": pyscf.__version__, "libxc": libxc.libxc_version(), "python": sys.executable}
    except Exception as exc:
        errors.append(f"Engine unavailable: {exc}")
    return {"engine": info, "errors": errors}


def check():
    executable = pipeline_python()
    if os.path.realpath(executable) == os.path.realpath(sys.executable):
        result = engine_check()
    else:
        command = [executable, "-c", "import json; from dfthub.doctor import engine_check; print(json.dumps(engine_check()))"]
        try:
            run = subprocess.run(command, capture_output=True, text=True, timeout=90, check=True)
            result = json.loads(run.stdout)
        except Exception as exc:
            result = {"engine": {}, "errors": [f"Compute Python check failed: {exc}"]}
    for name in ("static/index.html", "static/workspace/index.html", "static/analyze/index.html",
                 "static/vendor/swagger/swagger-ui-bundle.js", "resources/default_weights.csv",
                 "resources/optimizer/opt.py", "resources/optimizer/Database_updated/fit/W4-11"):
        if not (PACKAGE / name).is_file():
            result["errors"].append("Missing packaged resource: " + name)
    return result
