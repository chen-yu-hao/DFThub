"""CF22D in ORCA through its LibXC interface (ExtParamX / ExtParamC, ORCA >= 5.1).

The exchange and correlation components are selected by their LibXC names and
every external parameter is set explicitly.  ORCA must be linked against
LibXC >= 7.0, the first release with CF22D; the LibXC version is printed at
the top of the ORCA output and ``orca -libxcinfo hyb_mgga_x_cf22d`` lists the
parameters.  As a safeguard the exact-exchange fraction and the (unit)
scaling of the LibXC parts are also given explicitly with ScalHFX, ScalDFX,
ScalGGAC and ScalLDAC.

Not run in DFThub's tests; confirm the "LibXC version" and HF-fraction lines
of the first ORCA output.
"""
from __future__ import annotations

from .parameters import CF22DParameters, D3_ZERO, LIBXC_C_NAME, LIBXC_X_NAME


def _param_lines(keyword: str, named: dict) -> list:
    width = max(len(name) for name in named) + 2
    lines = []
    for name, value in named.items():
        quoted = f'"{name}"'
        lines.append(f"  {keyword} {quoted:<{width}} {value: .16e}")
    return lines


def render_input(params: CF22DParameters, basis: str = "def2-QZVP", with_d3: bool = True) -> str:
    keywords = f"! RKS {basis} DefGrid3"
    if with_d3:
        keywords += " D3ZERO"
    lines = [
        "# CF22D with DFThub-optimized parameters (ORCA >= 5.1 linked to LibXC >= 7.0)",
        f"# Parameter SHA-256: {params.sha256()}",
        "# Check the 'LibXC version' line and that the HF exchange fraction",
        f"# printed by ORCA equals {params.hf:.10f}.",
        keywords,
        "",
        "%method",
        "  Method      DFT",
        f"  Exchange    {LIBXC_X_NAME.lower()}",
        f"  Correlation {LIBXC_C_NAME.lower()}",
        *_param_lines("ExtParamX", params.libxc_x_named()),
        *_param_lines("ExtParamC", params.libxc_c_named()),
        f"  ScalHFX     {params.hf:.16e}  # exact exchange",
        "  ScalDFX     1.0                     # LibXC exchange enters unscaled",
        "  ScalGGAC    1.0",
        "  ScalLDAC    1.0",
    ]
    if with_d3:
        lines += [
            "  # CF22D D3 zero damping, no three-body term",
            f"  D3S6     {D3_ZERO['s6']}",
            f"  D3RS6    {D3_ZERO['rs6']}",
            f"  D3S8     {D3_ZERO['s8']}",
            f"  D3alpha6 {D3_ZERO['alpha6']:g}",
        ]
    lines += [
        "end",
        "",
        "* xyz 0 1",
        "  H 0.0 0.0 0.0",
        "  H 0.0 0.0 0.74",
        "*",
        "",
    ]
    return "\n".join(lines)
