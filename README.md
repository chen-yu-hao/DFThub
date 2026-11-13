# DFThub

DFThub example repository for applying optimized CF22D density-functional parameters in PySCF/libxc and in a licensed Gaussian 16 source build.

This repository demonstrates how to consume a DFThub `Parameters` file. It does not contain the CF22D training workflow or the complete data and scripts used to reproduce the cited paper.

## Quick start

On Linux with Python 3.10 or later:

```bash
git clone https://github.com/chen-yu-hao/DFThub.git
cd DFThub
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python CF22D_optimized_example.py
```

The last line printed should be `Total energy: -1.1634860046 Hartree`. On macOS, run the demo with `--no-d3`; on Windows, use WSL 2 (see [Platform notes](#platform-notes)).

## Contents

- `CF22D_optimized_example.py`: reads optimized parameters, registers a custom CF22D functional in PySCF/libxc, and optionally applies CF22D D3 zero-damping dispersion.
- `Parameters`: parameter file containing 40 `Cx`, 9 `Cy`, 9 `Cz`, and one `HF%` value.
- `dfthub_g16_builder.py`: patches a licensed Gaussian 16 source tree with values from `Parameters`, builds Gaussian 16, and writes the completed tree as `g16-opt/`.
- `requirements.txt`: Python dependencies for the PySCF example, pinned to the tested versions.
- `LICENSE`: MIT License text for the repository's original code and `Parameters` file. Gaussian 16 remains subject to its own license.

## System requirements

### PySCF example

| Requirement | Required or supported version | Tested configuration |
| --- | --- | --- |
| Operating system | 64-bit Linux; other systems are untested (see [Platform notes](#platform-notes)) | Ubuntu 24.04.2 LTS under WSL 2, Linux kernel 6.6.87.2 |
| Python | 3.10 or later; the exact pins in `requirements.txt` apply to 3.10–3.13 | 3.13.5 |
| NumPy | Compatible with the selected PySCF release | 2.1.3 |
| SciPy | Installed as a PySCF dependency | 1.15.3 |
| h5py | Installed as a PySCF dependency | 3.12.1 |
| PySCF | 2.13.1 or later, with libxc CF22D support | 2.13.1 with libxc 7.0.0 |
| `pyscf-dispersion` | Required when `with_d3=True`; PyPI provides Linux wheels only | 1.5.0 |
| Processor | Standard x86-64 CPU | Intel Core i7-14700, with 8 logical CPUs exposed to WSL 2 |
| Memory | At least 1 GiB available for the included H2 demo | 15 GiB installed; approximately 346 MiB peak resident memory during the demo |
| GPU | Not required | Not used |
| Disk | Allow at least 1 GiB for the Python environment and temporary installation files | The main installed numerical and PySCF packages occupied approximately 350 MiB |

No non-standard hardware is required for the PySCF example.

The numerical reference below was validated only with the exact tested versions in the table. Later PySCF, libxc, or dispersion implementations may require a new reference value even if the API remains compatible.

The demo was additionally run on 64-bit Linux with Python 3.10 and 3.13 (exact pins) and with Python 3.14.6 using NumPy 2.5.4, SciPy 1.18.1, h5py 3.16.0, PySCF 2.15.0 (libxc 7.1.2), and `pyscf-dispersion` 1.7.0; all reproduced the reference SCF energy below to every printed digit.

### Gaussian 16 builder

The builder additionally requires:

- Python 3.9 or later and `/bin/bash` on Linux;
- a valid Gaussian 16 license;
- a compatible, licensed Gaussian 16 source tree containing `bsd/g16.profile` and `bsd/bldg16`;
- the compilers, build tools, memory, and disk space required by that Gaussian 16 source distribution.

Gaussian 16 source code and binaries are not distributed by this repository. The full Gaussian build is environment-specific and was not included in the portable demo benchmark below.

## Installation

Clone the repository and create an isolated Python environment:

```bash
git clone https://github.com/chen-yu-hao/DFThub.git
cd DFThub
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

If GitHub is slow or unreachable from your network, the repository is also mirrored at `http://23.144.4.56:3334/chen-yu-hao/DFThub.git` (access to the mirror is restricted by source IP address).

`requirements.txt` selects dependency versions automatically:

- **Python 3.10–3.13:** the exact tested versions (`numpy==2.1.3`, `scipy==1.15.3`, `h5py==3.12.1`, `pyscf==2.13.1`, `pyscf-dispersion==1.5.0`).
- **Python 3.14 and later:** the pinned NumPy, SciPy, and h5py releases have no binary wheels for these Python versions, so current releases of `pyscf>=2.13.1` and `pyscf-dispersion` are installed instead.
- **Non-Linux systems:** `pyscf-dispersion` is skipped because PyPI provides it for Linux only.

Typical installation time is approximately 2–5 minutes on a standard desktop when binary wheels are available. This estimate excludes Python installation and any Gaussian 16 build.

### Platform notes

- **Linux (x86-64 or aarch64):** all dependencies, including `pyscf-dispersion`, provide binary wheels; this is the supported platform.
- **macOS:** NumPy, SciPy, h5py, and PySCF provide binary wheels, but `pyscf-dispersion` does not, so D3 dispersion is unavailable. Run the demo with `python CF22D_optimized_example.py --no-d3` and call `register_cf22d(mf, with_d3=False)` in your own scripts. This configuration is untested.
- **Windows:** PySCF does not provide native Windows wheels. Use WSL 2 (the tested configuration above) and follow the Linux instructions inside it.

Verify the installed versions:

```bash
python -c "import h5py, numpy, pyscf, scipy; print('NumPy', numpy.__version__); print('SciPy', scipy.__version__); print('h5py', h5py.__version__); print('PySCF', pyscf.__version__)"
python -c "from importlib.metadata import version; from pyscf.dft import libxc; print('libxc', libxc.__version__); print('pyscf-dispersion', version('pyscf-dispersion'))"
```

The repository is not installed as a Python package. Run the examples from the repository directory, or add that directory to `PYTHONPATH` when importing `CF22D_optimized_example.py` elsewhere.

## Demo

The included demo is a restricted Kohn–Sham calculation for H2 at a bond length of 0.74 Å. The geometry is embedded in `CF22D_optimized_example.py`; `Parameters` is the small accompanying input dataset. The calculation uses the `def2-qzvp` basis, PySCF grid level 6, the optimized parameters in `Parameters`, and CF22D D3 zero-damping dispersion.

Run:

```bash
python CF22D_optimized_example.py
```

The output should report DFTD3 use, SCF convergence, and end with approximately:

```text
Calc dispersion correction with DFTD3.
converged SCF energy = -1.16348600462391
Total energy: -1.1634860046 Hartree
```

With the exact tested software versions above, small platform-dependent differences in the last digits are possible; an absolute difference within `1e-8` Hartree from the value above is expected. Re-establish the reference value before applying this tolerance to other dependency versions. The script writes the detailed calculation log and final energy to standard output and does not intentionally create a persistent result file.

Expected run time is approximately 2 seconds on the tested desktop configuration. With PySCF reporting 8 threads, the measured wall time was 1.92 seconds with approximately 346 MiB peak resident memory.

The demo accepts a few options (`python CF22D_optimized_example.py --help`):

| Option | Effect |
| --- | --- |
| `--no-d3` | Run without D3 dispersion, for example where `pyscf-dispersion` is unavailable. |
| `--original` | Use the original published CF22D parameters embedded in the script instead of `Parameters`. |
| `--parameters PATH` | Use another DFThub parameter file. |

For this H2 geometry the D3 correction is only about −5 × 10⁻¹¹ Hartree, so `--no-d3` reports `converged SCF energy = -1.16348600457564`, which also agrees with the reference value above within the `1e-8` Hartree tolerance.

If PySCF is older than 2.13.1, or if D3 is requested but `pyscf-dispersion` is not installed, the script stops before the SCF calculation with a message explaining how to fix the environment.

## Use with your own calculation

Create the molecule and PySCF mean-field object normally, then call `register_cf22d` before `kernel`:

```python
from pyscf import dft, gto
from CF22D_optimized_example import register_cf22d

mol = gto.M(
    atom="H 0 0 0; H 0 0 0.74",
    basis="def2-qzvp",
    charge=0,
    spin=0,
)
mf = dft.RKS(mol)
mf.grids.level = 6

register_cf22d(mf, parameters_path="Parameters", with_d3=True)
energy = mf.kernel()
print(energy)
```

`register_cf22d` accepts RKS or UKS mean-field objects. It first checks the environment and raises `RuntimeError` with instructions if PySCF is older than 2.13.1, or if `with_d3=True` and `pyscf-dispersion` is not installed. On the supplied `mf` object it changes only the functional and dispersion settings; it also registers the custom functional name with libxc for the current Python process. Geometry, basis set, charge, spin, integration grid, SCF thresholds, memory, and output handling remain under the caller's control.

### Function arguments

| Argument | Meaning |
| --- | --- |
| `mf` | Required PySCF RKS or UKS mean-field object. |
| `name` | Internal libxc registration name; default: `cf22d_custom`. The value is converted to lowercase. |
| `parameters_path` | Path to a DFThub parameter file. By default, the `Parameters` file next to the Python module is used. An explicitly supplied relative path is resolved from the process working directory. Set to `None` to use the original published CF22D parameters embedded in the module instead of the optimized file. |
| `with_d3` | Enables the PySCF `d3zero:cf22d` correction when `True`; default: `True`. Set to `False` to run without dispersion. |

The custom-functional registry is process-wide. Registering another parameter set with the same `name` replaces the earlier definition, so use a unique name for each parameter set when comparing multiple functionals in one Python process.

For example, to use the embedded original parameter set without D3:

```python
register_cf22d(mf, parameters_path=None, with_d3=False)
```

`mf.kernel()` returns the total energy in Hartree and stores the normal PySCF results on `mf`. Use PySCF checkpoint or analysis functions if persistent orbitals, densities, or other outputs are required.

### `Parameters` input format

A complete file must contain:

- 40 `Cx(i,j,k)` assignments: `Cx(0,0,0..5)`, `Cx(0,1,0..4)`, `Cx(0,2,0..3)`, `Cx(0,3,0..2)`, `Cx(1,0,0..4)`, `Cx(1,1,0..3)`, `Cx(1,2,0..2)`, `Cx(2,0,0..3)`, `Cx(2,1,0..2)`, and `Cx(3,0,0..2)`;
- 9 assignments named `Cy(0)` through `Cy(8)`;
- 9 assignments named `Cz(0)` through `Cz(8)`;
- either `HF%` as a percentage or `HF` as a fractional exact-exchange coefficient.

Example:

```text
Cx(0,0,0) = -1.8691297464873982e-01
# ...the remaining Cx, Cy, and Cz entries...
HF% = 5.8103542452473214e+01
```

The PySCF reader accepts arbitrary whitespace, case-insensitive keys, `#` comments, and `E` or Fortran `D` exponents. It raises `ValueError` if any required key or the HF coefficient is missing. Unknown keys are ignored; if a recognized key occurs more than once, its last value is used.

`dfthub_g16_builder.py` reads the file with the same rules, matching values by key name, so the order of the entries does not matter for either path. The builder exits with an error instead of patching anything if a value cannot be parsed or a required key is missing.

## Gaussian 16 builder

This path is for users who are licensed and equipped to compile Gaussian 16. It is not required for the PySCF example.

Place the script, parameter file, and licensed source tree together:

```text
.
├── Parameters
├── dfthub_g16_builder.py
└── g16/
    ├── bsd/g16.profile
    ├── bsd/bldg16
    └── ...
```

If `g16/` is absent, the script extracts the first archive it finds in this order: `g16.tar.gz`, then `CF22Dg16.tar.gz`. It does not fall back to the second archive if extraction of the first one fails. Use only a trusted archive that you are licensed to possess.

Before running, make a separate backup of the clean source tree. Check the parameter file and the source tree without modifying anything:

```bash
python3 dfthub_g16_builder.py --dry-run
```

The dry run reports where each parameter block was found and how many lines would change. Then patch and build:

```bash
python3 dfthub_g16_builder.py
```

Use `--parameters PATH` to read a parameter file other than the `Parameters` file next to the script.

The script:

1. reads the 58 CF22D coefficients and HF value from `Parameters`, matching them by key name;
2. locates the expected CF22D source blocks in `g16/utilnz.F` and `g16/utilam.F`, including a nested `g16/g16/` source layout;
3. patches those source files in place;
4. sources `bsd/g16.profile` and runs `./bsd/bldg16`;
5. after a successful build, removes any existing `g16-opt/` and renames the top-level `g16/` directory to `g16-opt/`.

When preparing the source assignments, the builder reformats each of the 58 coefficients with 14 digits after the decimal point in scientific notation and rounds the HF fraction to the nearest `1e-6`. Consequently, the Gaussian source may contain slightly rounded values rather than every digit read by the PySCF path.

Successful output ends with messages similar to:

```text
✅ 编译 Gaussian16 完成
✅ 重命名为 g16-opt 完成
```

The expected persistent output is the `g16-opt/` source/build directory. Build time was not benchmarked because it depends on the licensed source release, compiler toolchain, processor, memory, and storage. Record it on the intended build system if the Gaussian path is part of a software submission.

Important behavior:

- Apart from `--parameters`, all paths (`g16/`, the source archives, and `g16-opt/`) are resolved relative to the script.
- It stops before writing if a required source block is missing or ambiguous.
- A later compiler failure does not roll back already patched source files.
- Existing `g16-opt/` is deleted only after the new build succeeds, immediately before the rename.

## Troubleshooting

- **`pyscf-dispersion` or DFTD3 is unavailable:** activate the intended environment and run `python -m pip install -r requirements.txt`. `pyscf-dispersion` is published for Linux only; on other systems use `--no-d3` / `with_d3=False`, and do so in production only when a calculation without dispersion is scientifically intended.
- **`CF22D requires PySCF >= 2.13.1`:** upgrade PySCF with `python -m pip install --upgrade "pyscf>=2.13.1"`. Older releases lack the CF22D custom-functional and D3 support used here.
- **pip tries to compile NumPy or SciPy, or fails looking for a Fortran compiler:** the exact pins have no wheels for Python 3.14 and later. Install with `python -m pip install -r requirements.txt` from this repository, which selects compatible versions automatically, or use Python 3.10–3.13 for the exact tested environment.
- **Installing on Windows fails:** PySCF has no native Windows wheels; use WSL 2.
- **`Incomplete Parameters file`:** check that all 40 `Cx`, 9 `Cy`, 9 `Cz`, and one `HF` or `HF%` assignment are present.
- **The Gaussian source block is missing or ambiguous:** use the compatible clean source release expected by the builder; an already modified or different source version may not match.
- **The Gaussian build fails after patching:** restore the clean backup before retrying with a corrected compiler or Gaussian build environment.
- **Cloning the mirror returns `403 Forbidden`:** the mirror at `23.144.4.56` restricts source IP addresses; clone from GitHub instead, use an authorized network, or request access from the mirror administrator.

## Reproducibility scope

The H2 demo above is the complete bundled quantitative test: it specifies the input geometry, basis, grid, optimized parameter file, dispersion setting, command, expected energy, tolerance, runtime, and tested software environment.

The repository does not include the datasets, preprocessing, fitting workflow, random seeds, or scripts needed to reproduce every table and figure in the referenced CF22D publication. Do not treat the H2 smoke test as a reproduction of the paper's full results.

## File structure

```text
.
├── CF22D_optimized_example.py
├── Parameters
├── dfthub_g16_builder.py
├── requirements.txt
├── LICENSE
└── README.md
```

## Reference

Y. Liu, C. Zhang, Z. Liu, D. G. Truhlar, Y. Wang, X. He, "Supervised Learning of a Chemistry Functional with Damped Dispersion", *Nature Computational Science*, 2023, 3, 48–58.

## License

The original code and `Parameters` file in this repository are made available under the MIT License. The full license text is provided in `LICENSE`. Gaussian 16 source code, Gaussian binaries, and third-party dependencies are not covered by this repository's license and remain subject to their respective terms.
