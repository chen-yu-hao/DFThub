"""Read CF22D parameter sets and apply them in quantum-chemistry programs.

* :mod:`.parameters` reads and writes DFThub ``Parameters`` files.
* :mod:`.pyscf` registers a parameter set on a PySCF mean-field object.
* :mod:`.gaussian` patches and builds a licensed Gaussian 16 source tree.
* :mod:`.orca` and :mod:`.psi4` write input files using LibXC parameters.
"""
from .parameters import (  # noqa: F401
    CF22DParameters, ParametersError, format_parameters, load_parameters, parse_parameters,
    read_parameters, write_parameters,
)

PROGRAMS = ("pyscf", "gaussian", "orca", "psi4")
DEFAULT_FILENAMES = {
    "pyscf": "CF22D_optimized.py",
    "gaussian": "cf22d.gjf",
    "orca": "cf22d.inp",
    "psi4": "cf22d_psi4.py",
}


def render(program: str, params: CF22DParameters, with_d3: bool = True, **options) -> str:
    """Input text that applies *params* in *program* (one of :data:`PROGRAMS`)."""
    if program == "pyscf":
        from .pyscf import render_script
        return render_script(params, with_d3=with_d3, **options)
    if program == "gaussian":
        from .gaussian import render_input
        return render_input(params, with_d3=with_d3, **options)
    if program == "orca":
        from .orca import render_input
        return render_input(params, with_d3=with_d3, **options)
    if program == "psi4":
        from .psi4 import render_input
        return render_input(params, with_d3=with_d3, **options)
    raise ValueError(f"Unknown program {program!r}; choose from {', '.join(PROGRAMS)}")
