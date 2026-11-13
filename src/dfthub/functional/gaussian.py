"""CF22D in Gaussian 16: patch a licensed source tree and build it.

Gaussian cannot read the 58 CF22D coefficients at run time, so they are
written into ``utilnz.F`` (exchange) and ``utilam.F`` (correlation and the
exact-exchange fraction ``IMHF``) of a licensed Gaussian 16 source tree that
is then rebuilt with ``bsd/bldg16``.  The patched blocks are the MN15 slots,
so the rebuilt Gaussian runs these parameters through the ``MN15`` keyword;
an unpatched Gaussian would silently run the original MN15 instead.

No PySCF import happens here.
"""
from __future__ import annotations

import shutil
import subprocess
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from .parameters import CF22DParameters, CX_KEYS, CY_KEYS, D3_ZERO

DEFAULT_ARCHIVES = ("g16.tar.gz", "CF22Dg16.tar.gz")
DEFAULT_KEYWORD = "MN15"


class GaussianBuildError(RuntimeError):
    """The Gaussian source tree, its CF22D blocks or the build is not usable."""


def fortran_values(params: CF22DParameters) -> Tuple[List[str], List[str], List[str], str]:
    """Source-ready strings: 40 Cx (``D`` exponent), 9 Cy and 9 Cz (``d``), IMHF.

    Coefficients keep 14 digits after the decimal point; IMHF is the HF
    fraction rounded to the nearest 1e-6 and written as six digits.
    """
    cx = [f"{v:.14e}".replace("e", "D") for v in params.cx]
    cy = [f"{v:.14e}".replace("e", "d") for v in params.cy]
    cz = [f"{v:.14e}".replace("e", "d") for v in params.cz]
    imhf = f"{int(round(params.hf * 1000000)):06d}"
    return cx, cy, cz, imhf


# ---------- locating the CF22D blocks ----------

def _compact(text: str) -> str:
    return "".join(text.split()).upper()


def _is_comment(line: str) -> bool:
    return line[:1] in ("C", "c", "*", "!")


def _assignment_key(line: str) -> Optional[str]:
    if _is_comment(line):
        return None
    left, sep, _ = line.partition("=")
    if not sep or left.lstrip().startswith("!"):
        return None
    return _compact(left)


def _find_deck(lines: List[str], name: str, src: Path) -> Tuple[int, int]:
    marker = _compact(f"*Deck {name}")
    matches = []
    for i, line in enumerate(lines):
        if _compact(line) == marker:
            end = next((j for j in range(i + 1, len(lines)) if _compact(lines[j]).startswith("*DECK")), len(lines))
            matches.append((i + 1, end))
    if len(matches) != 1:
        where = ", ".join(str(start) for start, _ in matches) or "none"
        raise GaussianBuildError(f"{src}: expected one {marker} deck, found {len(matches)} (lines: {where})")
    return matches[0]


def _find_section(lines: List[str], marker: str, src: Path, start: int = 0, end: Optional[int] = None) -> Tuple[int, int]:
    marker = _compact(marker)
    end = len(lines) if end is None else end
    matches = []
    for i in range(start, end):
        if _is_comment(lines[i]) or marker not in _compact(lines[i]):
            continue
        stop = end
        for j in range(i + 1, end):
            key = _compact(lines[j].lstrip())
            if key.startswith("ELSEIF(") or key == "ELSE":
                stop = j
                break
        matches.append((i + 1, stop))
    if len(matches) != 1:
        where = ", ".join(str(s) for s, _ in matches) or "none"
        raise GaussianBuildError(f"{src}: expected one {marker} block, found {len(matches)} (lines: {where})")
    return matches[0]


def _find_assignments(lines: List[str], keys: Sequence[str], src: Path, label: str,
                      start: int = 0, end: Optional[int] = None) -> int:
    keys = [_compact(k) for k in keys]
    end = len(lines) if end is None else end
    matches = [i for i in range(start, end - len(keys) + 1)
               if all(_assignment_key(lines[i + j]) == keys[j] for j in range(len(keys)))]
    if len(matches) != 1:
        where = ", ".join(str(i + 1) for i in matches) or "none"
        raise GaussianBuildError(f"{src}: expected one {label} parameter block, found {len(matches)} (lines: {where})")
    return matches[0]


def _replace(lines: List[str], index: int, value: str, key: str, src: Path) -> int:
    line = lines[index]
    left, sep, _ = line.partition("=")
    if not sep or _assignment_key(line) != _compact(key):
        raise GaussianBuildError(f"{src}, line {index + 1}: not the expected {key} assignment: {line.rstrip()}")
    new = left + f"= {value}\n"
    changed = new != line
    lines[index] = new
    return int(changed)


@dataclass
class PatchReport:
    utilnz: Path
    utilam: Path
    cx_lines: Tuple[int, int]
    cy_lines: Tuple[int, int]
    cz_lines: Tuple[int, int]
    imhf_line: int
    imhf: str
    changed: int
    written: bool
    notes: List[str] = field(default_factory=list)

    def summary(self) -> List[str]:
        lines = [
            f"Cx  : {self.utilnz} lines {self.cx_lines[0]}-{self.cx_lines[1]}",
            f"Cy  : {self.utilam} lines {self.cy_lines[0]}-{self.cy_lines[1]}",
            f"Cz  : {self.utilam} lines {self.cz_lines[0]}-{self.cz_lines[1]}",
            f"IMHF: {self.utilam} line {self.imhf_line} = {self.imhf}",
        ]
        verb = "changed" if self.written else "would change"
        lines.append(f"{self.changed} line(s) {verb}")
        return lines


def patch_sources(src: Path, params: CF22DParameters, dry_run: bool = False) -> PatchReport:
    """Write *params* into ``utilnz.F``/``utilam.F`` below *src*; nothing is written on error."""
    src = Path(src)
    nz, am = src / "utilnz.F", src / "utilam.F"
    if not nz.is_file() or not am.is_file():
        raise GaussianBuildError(f"utilnz.F or utilam.F not found in {src}")
    cx, cy, cz, imhf = fortran_values(params)
    nz_lines = nz.read_text().splitlines(True)
    am_lines = am.read_text().splitlines(True)

    deck_start, deck_end = _find_deck(nz_lines, "N12xP", nz)
    nx_start, nx_end = _find_section(nz_lines, "IFunc.eq.6", nz, deck_start, deck_end)
    cx_at = _find_assignments(nz_lines, CX_KEYS, nz, "Cx", nx_start, nx_end)
    cy_start, cy_end = _find_section(am_lines, "IFunc.eq.36", am)
    cy_at = _find_assignments(am_lines, CY_KEYS, am, "Cy", cy_start, cy_end)
    # Both correlation blocks name their coefficients CY(0..8) in the source.
    cz_start, cz_end = _find_section(am_lines, "IFunc.eq.37", am)
    cz_at = _find_assignments(am_lines, CY_KEYS, am, "Cz", cz_start, cz_end)
    hf_start, hf_end = _find_section(am_lines, "IMOpt.eq.-25", am)
    hf_at = _find_assignments(am_lines, ["IMHF"], am, "IMHF", hf_start, hf_end)

    changed = sum(_replace(nz_lines, cx_at + i, v, k, nz) for i, (k, v) in enumerate(zip(CX_KEYS, cx)))
    changed += sum(_replace(am_lines, cy_at + i, v, k, am) for i, (k, v) in enumerate(zip(CY_KEYS, cy)))
    changed += sum(_replace(am_lines, cz_at + i, v, k, am) for i, (k, v) in enumerate(zip(CY_KEYS, cz)))
    changed += _replace(am_lines, hf_at, imhf, "IMHF", am)

    if not dry_run:
        nz.write_text("".join(nz_lines))
        am.write_text("".join(am_lines))
    return PatchReport(nz, am, (cx_at + 1, cx_at + len(CX_KEYS)), (cy_at + 1, cy_at + 9),
                       (cz_at + 1, cz_at + 9), hf_at + 1, imhf, changed, not dry_run)


# ---------- source tree and build ----------

def _extract(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:*") as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(destination, filter="data")
        else:  # Python without PEP 706 support
            tar.extractall(destination)


def prepare_source(top: Path, archives: Sequence[Path] = ()) -> Path:
    """Return the Gaussian top directory, extracting the first existing archive if it is missing."""
    top = Path(top)
    if top.is_dir():
        return top
    archive = next((Path(a) for a in archives if Path(a).is_file()), None)
    if archive is None:
        names = ", ".join(str(a) for a in archives)
        raise GaussianBuildError(f"Gaussian source directory not found: {top}" + (f" (and no archive: {names})" if names else ""))
    _extract(archive, top.parent)
    if not top.is_dir():
        raise GaussianBuildError(f"{archive} did not contain {top.name}/")
    return top


def detect_source_root(top: Path) -> Path:
    """Directory holding ``bsd/g16.profile``: ``top/g16``, ``top``, or one found below it."""
    top = Path(top)
    for candidate in (top / "g16", top):
        if (candidate / "bsd" / "g16.profile").is_file():
            return candidate
    profile = next(top.rglob("bsd/g16.profile"), None)
    if profile is not None:
        return profile.parent.parent
    raise GaussianBuildError(f"No Gaussian source root (bsd/g16.profile) below {top}")


def build(src: Path, runner: Callable = subprocess.run) -> None:
    """Source ``bsd/g16.profile`` and run ``./bsd/bldg16`` in *src*."""
    src = Path(src).resolve()
    if src.name != "g16":
        raise GaussianBuildError(f"The Gaussian source root must be a directory named g16, not {src}")
    command = (
        f'export g16root="{src.parent}" && '
        'export GAUSS_EXEDIR="$g16root/g16" && '
        'source "$g16root/g16/bsd/g16.profile" && ./bsd/bldg16'
    )
    result = runner(command, shell=True, executable="/bin/bash", cwd=src)
    if result.returncode != 0:
        raise GaussianBuildError(f"bldg16 failed with exit code {result.returncode}; restore a clean source copy before retrying")


def finalize(top: Path, output: Path) -> Path:
    """Move the built tree to *output*, replacing an existing one."""
    top, output = Path(top), Path(output)
    if output.resolve() == top.resolve():
        return output
    shutil.rmtree(output, ignore_errors=True)
    top.rename(output)
    return output


# ---------- input template ----------

def d3_iops() -> str:
    """GD3 zero-damping IOps for the CF22D D3 parameters (-1 encodes zero)."""
    def iop(value):
        return int(round(value * 1000000)) or -1
    return f"IOp(3/174={iop(D3_ZERO['s6'])},3/175={iop(D3_ZERO['s8'])},3/176={iop(D3_ZERO['rs6'])})"


def render_input(params: CF22DParameters, keyword: str = DEFAULT_KEYWORD, basis: str = "def2QZVP",
                 with_d3: bool = True) -> str:
    """A ``.gjf`` template for a Gaussian built with these parameters (H2 geometry as placeholder)."""
    route = [f"#P {keyword}/{basis}"]
    if with_d3:
        route.append(f"EmpiricalDispersion=GD3 {d3_iops()}")
    title = [
        f"CF22D, DFThub parameters sha256 {params.sha256()[:16]}, HF={params.hf:.6f}",
        f"Run with a g16 built by 'dfthub g16 build'; {keyword} is the patched slot.",
        f"An unpatched Gaussian silently runs the original {keyword}.",
    ]
    if not with_d3:
        title.append("D3 dispersion disabled; CF22D is parameterized with D3(0).")
    return "\n".join([
        "%Chk=cf22d.chk",
        *route,
        "",
        *title,
        "",
        "0 1",
        "H 0.000000 0.000000 0.000000",
        "H 0.000000 0.000000 0.740000",
        "",
        "",
    ])
