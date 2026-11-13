"""CF22D parameter sets: the DFThub ``Parameters`` file and raw coefficient vectors.

A CF22D parameter set has 40 exchange coefficients ``Cx(i,j,k)``, 9 LSDA
correlation coefficients ``Cy(n)``, 9 PBE-LSDA correlation coefficients
``Cz(n)`` and the exact-exchange fraction ``HF``.  This module is the single
reader and writer for those values; it has no third-party dependencies so the
Gaussian and export commands work without the PySCF engine.
"""
from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

CX_DIMS = [
    (0, 0, 6), (0, 1, 5), (0, 2, 4), (0, 3, 3),
    (1, 0, 5), (1, 1, 4), (1, 2, 3),
    (2, 0, 4), (2, 1, 3),
    (3, 0, 3),
]
CX_INDICES = [(i, j, k) for i, j, n in CX_DIMS for k in range(n)]
CX_LABELS = [f"Cx({i},{j},{k})" for i, j, k in CX_INDICES]
CY_LABELS = [f"Cy({n})" for n in range(9)]
CZ_LABELS = [f"Cz({n})" for n in range(9)]

# Normalised keys used for lookup: no whitespace, upper case.
CX_KEYS = [label.upper() for label in CX_LABELS]
CY_KEYS = [label.upper() for label in CY_LABELS]
CZ_KEYS = [label.upper() for label in CZ_LABELS]
PARAM_KEYS = CX_KEYS + CY_KEYS + CZ_KEYS

# LibXC 7.0+ CF22D components and their external-parameter names.
LIBXC_X_ID, LIBXC_C_ID = 340, 341
LIBXC_X_NAME, LIBXC_C_NAME = "HYB_MGGA_X_CF22D", "MGGA_C_CF22D"
LIBXC_CX_PARAMS = [f"_CC{i}{j}{k}" for i, j, k in CX_INDICES]
LIBXC_HF_PARAM = "_ax"
LIBXC_CY_PARAMS = [f"_a{n}" for n in range(12)]
LIBXC_CZ_PARAMS = [f"_b{n}" for n in range(12)]

DEFAULT_HF = 0.462806

# CF22D is fitted together with D3 zero-damping dispersion without the
# three-body term; identical to PySCF's "d3zero:cf22d" and to the DFThub
# pipeline (dftd3 ZeroDampingParam(s6=1.0, s8=0.0, rs6=1.53, s9=0.0)).
D3_ZERO = {"s6": 1.0, "s8": 0.0, "rs6": 1.53, "rs8": 1.0, "alpha6": 14.0, "s9": 0.0}


class ParametersError(ValueError):
    """A parameter file or vector is missing values or cannot be parsed."""


def _compact(key: str) -> str:
    return "".join(key.split()).upper()


def _parse_float(raw: str) -> float:
    return float(raw.replace("D", "E").replace("d", "e"))


@dataclass(frozen=True)
class CF22DParameters:
    """One CF22D parameter set; ``hf`` is the exact-exchange fraction (0..1)."""

    cx: tuple
    cy: tuple
    cz: tuple
    hf: float

    def __post_init__(self):
        for name, values, count in (("Cx", self.cx, 40), ("Cy", self.cy, 9), ("Cz", self.cz, 9)):
            if len(values) != count:
                raise ParametersError(f"{name} needs {count} values, got {len(values)}")
        object.__setattr__(self, "cx", tuple(float(v) for v in self.cx))
        object.__setattr__(self, "cy", tuple(float(v) for v in self.cy))
        object.__setattr__(self, "cz", tuple(float(v) for v in self.cz))
        object.__setattr__(self, "hf", float(self.hf))
        if not all(math.isfinite(v) for v in self.vector()):
            raise ParametersError("CF22D parameters must be finite numbers")

    @classmethod
    def from_vector(cls, values: Sequence[float], default_hf: float = None) -> "CF22DParameters":
        """Build from the optimizer order: 40 Cx, 9 Cy, 9 Cz, then HF.

        A 58-value vector is accepted only when *default_hf* is given.
        """
        values = [float(v) for v in values]
        if len(values) == 58 and default_hf is not None:
            values.append(float(default_hf))
        if len(values) != 59:
            raise ParametersError(f"Expected 59 CF22D coefficients, got {len(values)}")
        return cls(values[:40], values[40:49], values[49:58], values[58])

    def vector(self) -> List[float]:
        """Optimizer order: 40 Cx, 9 Cy, 9 Cz, HF."""
        return [*self.cx, *self.cy, *self.cz, self.hf]

    @property
    def hf_percent(self) -> float:
        return self.hf * 100.0

    def sha256(self) -> str:
        """Hash of the little-endian float64 vector, as used by the DFThub pipeline."""
        return hashlib.sha256(struct.pack("<59d", *self.vector())).hexdigest()

    def labelled(self) -> Dict[str, float]:
        out = dict(zip(CX_LABELS, self.cx))
        out.update(zip(CY_LABELS, self.cy))
        out.update(zip(CZ_LABELS, self.cz))
        out["HF"] = self.hf
        return out

    def libxc_x_params(self) -> List[float]:
        """41 external parameters of HYB_MGGA_X_CF22D (40 Cx, then ``_ax``)."""
        return [*self.cx, self.hf]

    def libxc_c_params(self) -> List[float]:
        """24 external parameters of MGGA_C_CF22D (``_a0.._a11``, ``_b0.._b11``)."""
        return [*self.cy, 0.0, 0.0, 0.0, *self.cz, 0.0, 0.0, 0.0]

    def libxc_x_named(self) -> Dict[str, float]:
        return dict(zip(LIBXC_CX_PARAMS + [LIBXC_HF_PARAM], self.libxc_x_params()))

    def libxc_c_named(self) -> Dict[str, float]:
        return dict(zip(LIBXC_CY_PARAMS + LIBXC_CZ_PARAMS, self.libxc_c_params()))


def parse_parameters(text: str, source: str = "<string>") -> CF22DParameters:
    """Parse a DFThub ``Parameters`` file by key name.

    Ignores ``#`` comments, blank lines and unknown keys; keys are matched
    case- and whitespace-insensitively; ``E`` or Fortran ``D`` exponents are
    accepted; order is free and a repeated key keeps its last value.  The
    exact-exchange fraction is given either as ``HF%`` (percent) or ``HF``.
    """
    values: Dict[str, float] = {}
    hf = None
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        key, raw = (part.strip() for part in line.split("=", 1))
        key = _compact(key)
        if key not in ("HF", "HF%") and key not in PARAM_KEYS:
            continue
        try:
            number = _parse_float(raw)
        except ValueError:
            raise ParametersError(f"{source}, line {lineno}: cannot parse a number from {line!r}") from None
        if key == "HF%":
            hf = number / 100.0
        elif key == "HF":
            hf = number
        else:
            values[key] = number

    missing = [label for key, label in zip(PARAM_KEYS, CX_LABELS + CY_LABELS + CZ_LABELS) if key not in values]
    if hf is None:
        missing.append("HF% or HF")
    if missing:
        shown = ", ".join(missing[:5]) + (", ..." if len(missing) > 5 else "")
        raise ParametersError(f"Incomplete Parameters file {source}: missing {len(missing)} value(s): {shown}")
    return CF22DParameters([values[k] for k in CX_KEYS], [values[k] for k in CY_KEYS],
                           [values[k] for k in CZ_KEYS], hf)


def read_parameters(path) -> CF22DParameters:
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as exc:
        raise ParametersError(f"Cannot read Parameters file {path}: {exc.strerror or exc}") from None
    return parse_parameters(text, str(path))


def parse_vector(text: str, source: str = "<string>", default_hf: float = None) -> CF22DParameters:
    """Parse whitespace-separated coefficients (``NEW-params.txt`` / ``params.txt``)."""
    try:
        values = [_parse_float(token) for token in text.split()]
    except ValueError:
        raise ParametersError(f"{source}: coefficient files may contain only numbers") from None
    try:
        return CF22DParameters.from_vector(values, default_hf=default_hf)
    except ParametersError as exc:
        raise ParametersError(f"{source}: {exc}") from None


def read_vector(path, default_hf: float = None) -> CF22DParameters:
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as exc:
        raise ParametersError(f"Cannot read coefficient file {path}: {exc.strerror or exc}") from None
    return parse_vector(text, str(path), default_hf=default_hf)


def load_parameters(path) -> CF22DParameters:
    """Read either a ``Parameters`` file (``key = value``) or a raw 59-value vector."""
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as exc:
        raise ParametersError(f"Cannot read {path}: {exc.strerror or exc}") from None
    if "=" in text:
        return parse_parameters(text, str(path))
    return parse_vector(text, str(path))


def format_parameters(params: CF22DParameters) -> str:
    """Canonical ``Parameters`` text: 40 Cx, HF%, 9 Cy, 9 Cz."""
    lines = ["Parameters"]
    lines += [f"{label} = {value:.16e}" for label, value in zip(CX_LABELS, params.cx)]
    lines.append(f"HF% = {params.hf_percent:.16e}")
    lines += [f"{label} = {value:.16e}" for label, value in zip(CY_LABELS, params.cy)]
    lines += [f"{label} = {value:.16e}" for label, value in zip(CZ_LABELS, params.cz)]
    return "\n".join(lines) + "\n"


def write_parameters(params: CF22DParameters, path) -> None:
    Path(path).write_text(format_parameters(params))


def chunked(values: Iterable[float], size: int = 4) -> List[List[float]]:
    values = list(values)
    return [values[i:i + size] for i in range(0, len(values), size)]


# Parameter set embedded in the original CF22D_optimized_example.py and used
# by `--original`.  It is the optimizer's default starting point
# (resources/optimizer/params.txt) with HF = 0.462806; note that it differs
# from the native LibXC CF22D defaults.
ORIGINAL = CF22DParameters(
    cx=(
        3.420465997641110e-01, -6.403129726319901e-01, -9.343258286278120e-01, 2.548116332532230e-01,
        4.037942894981320e-01, 1.269312660000240e+00, 8.550102386275800e-02, -5.210700505353760e+00,
        -4.877609897602050e+00, -8.107937437626570e-01, 3.200067528069070e+00, -2.084116683362500e+00,
        -3.442955759357800e+00, -6.584525141174520e+00, 4.311580561114060e+00, 4.001780465506710e+00,
        -5.068257715480800e+00, -4.609538322325340e+00, 3.666974512750690e-01, 1.688404715603940e+00,
        1.132276274126880e+00, -6.644212396547720e-01, -8.542839602750379e-01, 2.228546690696300e+00,
        7.428226613038940e+00, 3.424630827360860e+00, -1.503891451116870e-01, -1.702216036299310e+00,
        -1.721828984322240e+00, 3.449962934107250e+00, -3.510995342270110e-01, -1.290159050757220e+00,
        2.296377003659940e+00, -1.449908779871820e+00, -1.036610748098920e+00, 2.386536009979160e+00,
        8.631845365492721e+00, 5.261947471262800e-02, -1.119462650428560e+00, -3.091283450748370e+00,
    ),
    cy=(
        8.725507563372000e-01, 4.468998640960900e-01, 4.491910770052130e+00, -9.931144521225890e-01,
        -2.726339657477250e+00, -1.936735776514450e-01, 4.431633587771830e-01, -2.310484724823420e+00,
        2.064573581116490e-01,
    ),
    cz=(
        8.854855109687830e-01, -1.209725372266990e+00, 5.453278568094860e+00, -3.151355204738420e-01,
        -3.175066008038980e+00, 3.105458838276020e+00, -1.385493176417390e+00, -9.015986018178800e-02,
        2.427372033636820e+00,
    ),
    hf=DEFAULT_HF,
)
