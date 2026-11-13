"""Deprecated: use ``dfthub.functional.pyscf`` or ``dfthub pyscf demo``.

Kept for one release so existing imports keep working; the implementation
now lives in ``dfthub.functional``.

    from pyscf import gto, dft
    from CF22D_optimized_example import register_cf22d

    mol = gto.M(atom="H 0 0 0; H 0 0 0.74", basis="def2-qzvp")
    mf = dft.RKS(mol)
    mf.grids.level = 6
    register_cf22d(mf)                 # ./Parameters next to this file + D3
    mf.kernel()

Command line (H2 demo), equivalent to ``dfthub pyscf demo``::

    python CF22D_optimized_example.py [--parameters PATH | --original] [--no-d3]

Reference: Y. Liu, C. Zhang, Z. Liu, D. G. Truhlar, Y. Wang, X. He,
Nat. Comput. Sci., 2023, 3, 48-58.
"""
import sys
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent
if (_BASE_DIR / "src" / "dfthub").is_dir():
    sys.path.insert(0, str(_BASE_DIR / "src"))

import numpy as np  # noqa: E402

from dfthub.functional.parameters import (  # noqa: E402
    CX_KEYS, CY_KEYS, CZ_KEYS, ORIGINAL, read_parameters,
)
from dfthub.functional.pyscf import (  # noqa: E402
    CF22D_D3_DISPERSION, MIN_PYSCF_VERSION, check_requirements,
    register_cf22d as _register_cf22d,
)

DEFAULT_PARAMETERS_PATH = _BASE_DIR / "Parameters"
CX = np.array(ORIGINAL.cx)
CY = np.array(ORIGINAL.cy)
CZ = np.array(ORIGINAL.cz)
HF_COEFF = ORIGINAL.hf

__all__ = [
    "CF22D_D3_DISPERSION", "CX", "CX_KEYS", "CY", "CY_KEYS", "CZ", "CZ_KEYS", "DEFAULT_PARAMETERS_PATH",
    "HF_COEFF", "MIN_PYSCF_VERSION", "check_requirements", "read_cf22d_parameters", "register_cf22d",
]


def read_cf22d_parameters(path=DEFAULT_PARAMETERS_PATH):
    """Return ``(cx, cy, cz, hf_coeff)`` from a DFThub ``Parameters`` file."""
    params = read_parameters(path)
    return np.array(params.cx), np.array(params.cy), np.array(params.cz), params.hf


def register_cf22d(mf, name="cf22d_custom", parameters_path=DEFAULT_PARAMETERS_PATH, with_d3=True):
    """Apply CF22D to *mf*; ``parameters_path=None`` uses the embedded original set."""
    parameters = None if parameters_path is None else read_parameters(parameters_path)
    return _register_cf22d(mf, parameters, name=name, with_d3=with_d3)


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Deprecated wrapper for `dfthub pyscf demo`.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--parameters", metavar="PATH", default=str(DEFAULT_PARAMETERS_PATH))
    source.add_argument("--original", action="store_true")
    parser.add_argument("--no-d3", action="store_true")
    args = parser.parse_args(argv)
    print("CF22D_optimized_example.py is deprecated; use `dfthub pyscf demo`.", file=sys.stderr)

    from dfthub.cli import main as dfthub_main

    command = ["pyscf", "demo"] + (["--original"] if args.original else ["--parameters", args.parameters])
    if args.no_d3:
        command.append("--no-d3")
    return dfthub_main(command)


if __name__ == "__main__":
    raise SystemExit(main())
