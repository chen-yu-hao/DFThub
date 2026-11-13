"""CF22D in PySCF/LibXC: register a parameter set on a mean-field object.

PySCF is imported only when a function here needs it, so the rest of
``dfthub.functional`` stays usable without the DFT engine.
"""
from __future__ import annotations

import os
from pathlib import Path
import platform
import re
from string import Template
import sys
import types

if sys.platform.startswith("linux") and platform.machine().lower() in ("x86_64", "amd64"):
    os.environ.setdefault("OPENBLAS_CORETYPE", "Haswell")

from .parameters import (
    CF22DParameters, D3_ZERO, LIBXC_C_ID, LIBXC_X_ID, ORIGINAL, chunked, load_parameters,
)

CF22D_D3_DISPERSION = "d3zero:cf22d"
CF22D_D3_S6 = 0.4889916
CF22D_D3_SR6 = 1.9462247
CF22D_D3_S8 = 0.0
MIN_PYSCF_VERSION = (2, 13, 1)

D3_INSTALL_HINT = (
    "D3 dispersion (with_d3=True) requires pyscf-dispersion or dftd3 (simple-dftd3). "
    "With the DFThub engine install it without dependencies so pip does not pull in upstream pyscf: "
    "'python -m pip install --no-deps pyscf-dispersion'; with upstream PySCF use "
    "'python -m pip install pyscf-dispersion'. PyPI ships Linux wheels only. "
    "Use with_d3=False (command line: --no-d3) to run without dispersion."
)


def _version_tuple(version):
    match = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", version)
    if match is None:
        return None
    return tuple(int(part or 0) for part in match.groups())


def _enable_dftd3_dispersion(mf=None):
    try:
        from pyscf.dispersion import dftd3  # noqa: F401
        return
    except ImportError:
        try:
            import dftd3.pyscf as disp
        except ImportError as err:
            raise RuntimeError(D3_INSTALL_HINT) from err

    from pyscf.scf import dispersion as scf_disp

    class _DFTD3Adapter:
        class DFTD3Dispersion(disp.DFTD3Dispersion):
            def get_dispersion(self, grad=False):
                energy, gradient, _ = self.kernel()
                return {"energy": float(energy), "gradient": gradient}

    scf_disp.dftd3 = _DFTD3Adapter
    if "pyscf.dispersion" not in sys.modules:
        mod = types.ModuleType("pyscf.dispersion")
        mod.dftd3 = _DFTD3Adapter
        mod.dftd4 = getattr(scf_disp, "dftd4", None)
        sys.modules["pyscf.dispersion"] = mod
    if mf is not None:
        param = {"s6": D3_ZERO["s6"], "s8": D3_ZERO["s8"], "rs6": D3_ZERO["rs6"], "s9": 0.0}
        mf.with_dftd3 = disp.DFTD3Dispersion(mf.mol, version="d3zero", atm=False, param=param)
        if hasattr(mf, "_keys"):
            mf._keys.add("with_dftd3")


def check_requirements(with_d3=True):
    """Fail early, with an actionable message, if PySCF cannot run CF22D."""
    try:
        import pyscf
    except ImportError as err:
        raise RuntimeError("PySCF is not installed; install the DFThub engine (dfthub-pyscf-dft)") from err
    found = _version_tuple(pyscf.__version__)
    if found is not None and found < MIN_PYSCF_VERSION:
        required = ".".join(map(str, MIN_PYSCF_VERSION))
        raise RuntimeError(f"CF22D requires PySCF >= {required} (found {pyscf.__version__})")
    if with_d3:
        _enable_dftd3_dispersion()


def _as_parameters(parameters):
    if parameters is None:
        return ORIGINAL
    if isinstance(parameters, CF22DParameters):
        return parameters
    return load_parameters(parameters)


def register_cf22d(mf, parameters=None, name="cf22d_custom", with_d3=True):
    """Register a CF22D parameter set with LibXC and apply it to *mf*.

    *parameters* is a :class:`CF22DParameters`, a path to a ``Parameters`` file
    (or raw 59-value vector), or ``None`` for the embedded original set.  Only
    ``mf.xc`` and ``mf.disp`` change; the LibXC registration is process-wide,
    so use a distinct *name* per parameter set.
    """
    check_requirements(with_d3)
    import numpy as np
    from pyscf.dft import libxc

    params = _as_parameters(parameters)
    name = name.lower()
    libxc.register_custom_functional_(
        name, "CF22D,CF22D",
        ext_params={LIBXC_X_ID: np.array(params.libxc_x_params()), LIBXC_C_ID: np.array(params.libxc_c_params())},
    )
    mf.xc = name
    if with_d3:
        _enable_dftd3_dispersion(mf)
        mf.disp = CF22D_D3_DISPERSION
    else:
        mf.disp = False
    return mf


apply_cf22d = register_cf22d


def run_demo(parameters=None, with_d3=True, verbose=4):
    """RKS H2 at 0.74 Angstrom, def2-QZVP, grid level 6; returns the total energy."""
    from pyscf import dft, gto

    mol = gto.M(atom="H 0 0 0; H 0 0 0.74", basis="def2-qzvp", verbose=verbose)
    mf = dft.RKS(mol)
    mf.grids.level = 6
    register_cf22d(mf, parameters, with_d3=with_d3)
    mf.kernel()
    if not mf.converged:
        raise RuntimeError("SCF did not converge")
    return float(mf.e_tot)


def _array(values):
    return "\n".join("    " + ", ".join(f"{v: .16e}" for v in row) + "," for row in chunked(values))


SCRIPT_TEMPLATE = Template('''\
"""CF22D functional with DFThub-optimized parameters.

${dataset_line}\
Parameter SHA-256: $sha256
Generated by DFThub  https://github.com/chen-yu-hao/DFThub

Requirements: PySCF >= 2.13.1 with LibXC CF22D support (LibXC >= 7.0); D3
dispersion additionally needs pyscf-dispersion or dftd3.

Usage
-----
    from pyscf import gto, dft
    from CF22D_optimized import register_cf22d

    mol = gto.M(atom="H 0 0 0; H 0 0 0.74", basis="def2-qzvp")
    mf = dft.RKS(mol)
    mf.grids.level = 6
    register_cf22d(mf)            # functional + CF22D D3(0) dispersion
    mf.kernel()

Command line (H2 demo)::

    python CF22D_optimized.py [--no-d3]
"""

import os
import platform
import sys
import types

if sys.platform.startswith("linux") and platform.machine().lower() in ("x86_64", "amd64"):
    os.environ.setdefault("OPENBLAS_CORETYPE", "Haswell")

import numpy as np
from pyscf.dft import libxc

# 40 exchange coefficients  (Cx: _CC000 .. _CC302)
CX = np.array([
$cx
])

# 9 LSDA correlation coefficients  (Cy: _a0 .. _a8)
CY = np.array([
$cy
])

# 9 PBE-LSDA correlation coefficients  (Cz: _b0 .. _b8)
CZ = np.array([
$cz
])

# HF exact-exchange mixing coefficient
HF_COEFF = $hf

# D3 zero damping, no three-body term: s6=$s6, s8=$s8, rs6=$rs6
D3_DISPERSION = "$d3"
D3_PARAM = {"s6": $s6, "s8": $s8, "rs6": $rs6, "s9": 0.0}
WITH_D3 = $with_d3


def _register_functional(mf, name):
    x_params = np.zeros(41)
    x_params[:40] = CX
    x_params[40] = HF_COEFF

    c_params = np.zeros(24)
    c_params[:9] = CY
    c_params[12:21] = CZ

    name = name.lower()  # PySCF lowercases xc names internally
    libxc.register_custom_functional_(
        name,
        "CF22D,CF22D",
        ext_params={$x_id: x_params, $c_id: c_params},
    )
    mf.xc = name
    return mf


def _enable_dftd3(mf, disp):
    from pyscf.scf import dispersion as scf_disp

    class _DFTD3Adapter:
        class DFTD3Dispersion(disp.DFTD3Dispersion):
            def get_dispersion(self, grad=False):
                energy, gradient, _ = self.kernel()
                return {"energy": float(energy), "gradient": gradient}

    scf_disp.dftd3 = _DFTD3Adapter
    if "pyscf.dispersion" not in sys.modules:
        mod = types.ModuleType("pyscf.dispersion")
        mod.dftd3 = _DFTD3Adapter
        mod.dftd4 = getattr(scf_disp, "dftd4", None)
        sys.modules["pyscf.dispersion"] = mod
    mf.with_dftd3 = disp.DFTD3Dispersion(mf.mol, version="d3zero", atm=False, param=D3_PARAM)
    if hasattr(mf, "_keys"):
        mf._keys.add("with_dftd3")


def register_cf22d(mf, name="cf22d_custom", with_d3=WITH_D3):
    """Apply the optimized CF22D functional and, by default, its D3(0) dispersion."""
    disp_mod = None
    if with_d3:
        try:
            from pyscf.dispersion import dftd3  # noqa: F401
        except ImportError:
            try:
                import dftd3.pyscf as disp_mod
            except ImportError as err:
                raise RuntimeError(
                    "D3 dispersion needs pyscf-dispersion or dftd3 (with the DFThub engine: "
                    "python -m pip install --no-deps pyscf-dispersion); "
                    "or pass with_d3=False / --no-d3."
                ) from err
    _register_functional(mf, name)
    mf.disp = D3_DISPERSION if with_d3 else False
    if with_d3 and disp_mod is not None:
        _enable_dftd3(mf, disp_mod)
    return mf


def register_cf22d_srp(mf, name="cf22d_srp"):
    """Apply only the exchange-correlation functional; ``mf.disp`` is left unchanged.

    The DFThub pipeline uses this entry point and adds D3 itself.
    """
    return _register_functional(mf, name)


if __name__ == "__main__":
    import argparse

    from pyscf import dft, gto

    parser = argparse.ArgumentParser(description="CF22D H2 demo (RKS/def2-QZVP, grid level 6, R = 0.74 Angstrom)")
    parser.add_argument("--no-d3", action="store_true", help="run without D3 dispersion")
    args = parser.parse_args()

    mol = gto.M(atom="H 0 0 0; H 0 0 0.74", basis="def2-qzvp", verbose=4)
    mf = dft.RKS(mol)
    mf.grids.level = 6
    register_cf22d(mf, with_d3=WITH_D3 and not args.no_d3)
    mf.kernel()
    print(f"Total energy: {mf.e_tot:.10f} Hartree")
''')


def render_script(params: CF22DParameters, dataset_name: str = "", with_d3: bool = True) -> str:
    """Standalone PySCF module for *params*; also used for the web export CF22D_optimized.py."""
    return SCRIPT_TEMPLATE.substitute(
        dataset_line=f"Dataset: {dataset_name}\n" if dataset_name else "",
        sha256=params.sha256(),
        cx=_array(params.cx), cy=_array(params.cy), cz=_array(params.cz),
        hf=repr(params.hf),
        s6=D3_ZERO["s6"], s8=D3_ZERO["s8"], rs6=D3_ZERO["rs6"],
        d3=CF22D_D3_DISPERSION, with_d3=bool(with_d3),
        x_id=LIBXC_X_ID, c_id=LIBXC_C_ID,
    )


render_pyscf_script = render_script


def write_script(params: CF22DParameters, path, dataset_name: str = "", with_d3: bool = True) -> Path:
    path = Path(path)
    path.write_text(render_script(params, dataset_name=dataset_name, with_d3=with_d3))
    return path
