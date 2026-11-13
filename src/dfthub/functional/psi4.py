"""CF22D in Psi4 as a custom functional dictionary with LibXC tweaks.

Psi4 builds the functional from ``HYB_MGGA_X_CF22D`` and ``MGGA_C_CF22D``
(LibXC >= 7.0) with every external parameter given in ``"tweak"``.  The exact
exchange is set through ``"x_hf"`` with ``"use_libxc": False``: Psi4 reads a
LibXC hybrid coefficient before applying tweaks, so relying on LibXC would
silently keep the default 0.462806.  The D3 correction uses Psi4's
``d3zero2b`` (zero damping, no three-body term) with the CF22D parameters.

Not run in DFThub's tests; Psi4 must be linked against LibXC >= 7.0.
"""
from __future__ import annotations

from .parameters import CF22DParameters, D3_ZERO, LIBXC_C_NAME, LIBXC_X_NAME


def _tweak_lines(named: dict, indent: str) -> list:
    return [f'{indent}"{name}": {value!r},' for name, value in named.items()]


def render_input(params: CF22DParameters, basis: str = "def2-qzvp", with_d3: bool = True) -> str:
    lines = [
        '"""CF22D with DFThub-optimized parameters for Psi4 (LibXC >= 7.0).',
        "",
        f"Parameter SHA-256: {params.sha256()}",
        "Run with:  python cf22d_psi4.py   (or psi4 cf22d_psi4.py)",
        '"""',
        "import psi4",
        "",
        "CF22D_DFTHUB = {",
        '    "name": "CF22D-DFTHUB",',
        '    "description": "    CF22D with DFThub-optimized parameters\\n",',
        '    "x_functionals": {',
        f'        "{LIBXC_X_NAME}": {{',
        '            "use_libxc": False,  # exact exchange comes from "x_hf" below',
        '            "tweak": {',
        *_tweak_lines(params.libxc_x_named(), " " * 16),
        "            },",
        "        },",
        "    },",
        f'    "x_hf": {{"alpha": {params.hf!r}}},',
        '    "c_functionals": {',
        f'        "{LIBXC_C_NAME}": {{',
        '            "tweak": {',
        *_tweak_lines(params.libxc_c_named(), " " * 16),
        "            },",
        "        },",
        "    },",
    ]
    if with_d3:
        lines += [
            '    "dispersion": {',
            '        "type": "d3zero2b",',
            '        "params": {'
            f'"s6": {D3_ZERO["s6"]!r}, "s8": {D3_ZERO["s8"]!r}, "sr6": {D3_ZERO["rs6"]!r}, '
            f'"sr8": {D3_ZERO["rs8"]!r}, "alpha6": {D3_ZERO["alpha6"]!r}' "},",
            "    },",
        ]
    lines += [
        "}",
        "",
        "if __name__ == \"__main__\":",
        "    psi4.set_memory(\"2 GB\")",
        "    psi4.geometry(\"\"\"",
        "    0 1",
        "    H 0.0 0.0 0.0",
        "    H 0.0 0.0 0.74",
        "    \"\"\")",
        f'    psi4.set_options({{"basis": "{basis}", "reference": "rks", "dft_spherical_points": 590, "dft_radial_points": 99}})',
        '    energy = psi4.energy("scf", dft_functional=CF22D_DFTHUB)',
        '    print(f"Total energy: {energy:.10f} Hartree")',
        "",
    ]
    return "\n".join(lines)
