"""Check actual imported code and native libraries, not just a version string."""
import hashlib
import importlib.metadata as md
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from .paths import PACKAGE, pipeline_python

if sys.platform.startswith("linux") and platform.machine().lower() in ("x86_64", "amd64"):
    os.environ.setdefault("OPENBLAS_CORETYPE", "Haswell")

COMMIT = "e7cb735789293acf461f8ebbb4ac6a08b68ba5d6"
ENGINE_VERSION = "2.14.0+dfthub.e7cb7357"
H2_DEF2_QZVP_REF_ENERGY = -1.16348600462391
H2_DEF2_QZVP_REF_PARAMS = (
    -1.8691297464873982e-01, -2.7949032161241621e-01,  1.0546864787149583e-01,  1.6202727356557396e+00,
     1.2431357343377572e-01,  7.2481346262841395e-01,  2.3194432006130561e+00, -6.7174934887080404e+00,
    -4.2523292617419886e+00,  9.3511317473011246e+00,  1.4704576019458159e+01, -9.9125004720613177e+00,
    -1.1208189598918956e+01, -7.4985459960435712e+00,  6.5964888694323500e+00, -9.6695904533102373e-01,
    -1.8333852981317587e+01, -1.2456628629634880e+01,  2.1927764608867668e+00, -6.7070564845093672e-01,
    -5.1614028092934738e+00, -6.8773285579456953e+00,  8.5316487924539086e-01, -1.5690129915096434e+00,
     8.5829230795535025e+00,  7.2449657307306810e+00,  1.9469789402146876e+01,  8.8697880516741581e+00,
     9.5349647073561012e+00,  1.3430795987850543e+01, -2.5740619015254107e+00,  3.5471394527160416e+00,
     9.4215300293395750e+00,  3.3991971121178355e+00, -1.7610266407628874e+00, -4.5252747948007138e-01,
     1.6992223831347420e+01,  9.6619247902278427e-01, -4.0908116336268865e+00, -4.5182549070054634e+00,
     9.4788150915534053e-01, -2.2722277355078528e-02,  6.6231612333539251e+00,  2.3466897040646435e+00,
    -7.7721658884549960e-01, -3.8537055836409384e-01, -2.8816777603308347e-01, -2.9700229127267961e+00,
     2.0250807515535514e+00,
     1.2885635117480587e+00, -4.8652127081555531e-01,  1.2352820680010815e+01,  5.2087869530924031e+00,
    -4.9634660263868380e+00,  9.6782511597001157e+00,  8.4519776110026807e+00,  1.7016170824368182e+01,
     2.1755410885538375e+01,
     0.5810354245247321,
)


def _check_h2_def2_qzvp():
    from pyscf import dft, gto
    from .functional.parameters import CF22DParameters
    from .functional.pyscf import register_cf22d

    mol = gto.M(atom="H 0 0 0; H 0 0 0.74", basis="def2-qzvp", verbose=0)
    mf = dft.RKS(mol)
    mf.grids.level = 6
    params = CF22DParameters.from_vector(H2_DEF2_QZVP_REF_PARAMS)
    register_cf22d(mf, params, name="cf22d_doctor_check", with_d3=False)
    energy = float(mf.kernel())
    error = abs(energy - H2_DEF2_QZVP_REF_ENERGY)
    if not mf.converged or error >= 1e-6:
        raise RuntimeError(
            f"H2/def2-qzvp energy check failed: got {energy:.10f} Eh "
            f"(expected {H2_DEF2_QZVP_REF_ENERGY:.10f} Eh, |err|={error:.3e})"
        )
    return energy


def engine_check(strict=False):
    if sys.platform.startswith("linux") and platform.machine().lower() in ("x86_64", "amd64"):
        os.environ.setdefault("OPENBLAS_CORETYPE", "Haswell")
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
        if strict:
            _check_h2_def2_qzvp()
        from dftd3.interface import DispersionModel, ZeroDampingParam
        from xclib.CFXXD import CF22D_nxc, CF22D_nxc_rks
        import threadpoolctl
        from pyscf.dft import numa
        from pyscf.scf import eri_cache
        info = {"branch": manifest["branch"], "commit": manifest["commit"],
                "pyscf": pyscf.__version__, "libxc": libxc.libxc_version(),
                "threadpoolctl": threadpoolctl.__version__, "python": sys.executable}
    except Exception as exc:
        errors.append(f"Engine unavailable: {exc}")
    return {"engine": info, "errors": errors}


def check(strict=False):
    executable = pipeline_python()
    if os.path.realpath(executable) == os.path.realpath(sys.executable):
        result = engine_check(strict=strict)
    else:
        command = [
            executable, "-c",
            f"import json; from dfthub.doctor import engine_check; print(json.dumps(engine_check(strict={bool(strict)!r})))",
        ]
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


def collect_report(strict=False):
    return check(strict=strict)
