# DFThub

DFThub example repository for applying optimized CF22D density-functional parameters in PySCF/libxc and in a licensed Gaussian 16 source build.

This repository demonstrates how to consume a DFThub `Parameters` file. It does not contain the CF22D training workflow or the complete data and scripts used to reproduce the cited paper.

## Contents

- `CF22D_optimized_example.py`: reads optimized parameters, registers a custom CF22D functional in PySCF/libxc, and optionally applies CF22D D3 zero-damping dispersion.
- `Parameters`: parameter file containing 40 `Cx`, 9 `Cy`, 9 `Cz`, and one `HF%` value.
- `dfthub_g16_builder.py`: patches a licensed Gaussian 16 source tree with values from `Parameters`, builds Gaussian 16, and writes the completed tree as `g16-opt/`.
- `LICENSE`: MIT License text for the repository's original code and `Parameters` file. Gaussian 16 remains subject to its own license.

## System requirements

### PySCF example

| Requirement | Required or supported version | Tested configuration |
| --- | --- | --- |
| Operating system | 64-bit Linux; other systems are untested | Ubuntu 24.04.2 LTS under WSL 2, Linux kernel 6.6.87.2 |
| Python | 3.10 or later | 3.13.5 |
| NumPy | Compatible with the selected PySCF release | 2.1.3 |
| SciPy | Installed as a PySCF dependency | 1.15.3 |
| h5py | Installed as a PySCF dependency | 3.12.1 |
| PySCF | 2.13.1 or later, with libxc CF22D support | 2.13.1 with libxc 7.0.0 |
| `pyscf-dispersion` | Required when `with_d3=True` | 1.5.0 |
| Processor | Standard x86-64 CPU | Intel Core i7-14700, with 8 logical CPUs exposed to WSL 2 |
| Memory | At least 1 GiB available for the included H2 demo | 15 GiB installed; approximately 346 MiB peak resident memory during the demo |
| GPU | Not required | Not used |
| Disk | Allow at least 1 GiB for the Python environment and temporary installation files | The main installed numerical and PySCF packages occupied approximately 350 MiB |

No non-standard hardware is required for the PySCF example.

The numerical reference below was validated only with the exact tested versions in the table. Later PySCF, libxc, or dispersion implementations may require a new reference value even if the API remains compatible.

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
git clone http://23.144.4.56:3334/chen-yu-hao/DFThub.git
cd DFThub
python3 -m venv .venv
source .venv/bin/activate
python -m pip install numpy==2.1.3 scipy==1.15.3 h5py==3.12.1 pyscf==2.13.1 pyscf-dispersion==1.5.0
```

Typical installation time is approximately 2–5 minutes on a standard desktop when binary wheels are available. This estimate excludes Python installation and any Gaussian 16 build.

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

`register_cf22d` accepts RKS or UKS mean-field objects. On the supplied `mf` object it changes only the functional and dispersion settings; it also registers the custom functional name with libxc for the current Python process. Geometry, basis set, charge, spin, integration grid, SCF thresholds, memory, and output handling remain under the caller's control.

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

For compatibility with `dfthub_g16_builder.py`, retain the canonical order used by the provided file: 40 `Cx` values, `HF%`, 9 `Cy` values, then 9 `Cz` values, using standard `E`-notation numbers. The Gaussian builder consumes the 58 non-HF numeric assignments by file order.

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

Before running, make a separate backup of the clean source tree. Then run:

```bash
python3 dfthub_g16_builder.py
```

The script:

1. reads the 58 CF22D coefficients and HF value from `Parameters`;
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

- The script has no command-line options; all paths are resolved relative to the script.
- It stops before writing if a required source block is missing or ambiguous.
- A later compiler failure does not roll back already patched source files.
- Existing `g16-opt/` is deleted only after the new build succeeds, immediately before the rename.

## Troubleshooting

- **`pyscf-dispersion` or DFTD3 is unavailable:** activate the intended environment and install `pyscf-dispersion==1.5.0`. Use `with_d3=False` only when a calculation without dispersion is scientifically intended.
- **CF22D is unknown to libxc:** install PySCF 2.13.1 or later and confirm that its libxc build provides CF22D.
- **`Incomplete Parameters file`:** check that all 40 `Cx`, 9 `Cy`, 9 `Cz`, and one `HF` or `HF%` assignment are present.
- **The Gaussian source block is missing or ambiguous:** use the compatible clean source release expected by the builder; an already modified or different source version may not match.
- **The Gaussian build fails after patching:** restore the clean backup before retrying with a corrected compiler or Gaussian build environment.
- **Cloning returns `403 Forbidden`:** the configured repository mirror restricts source IP addresses; use an authorized network or request access from the mirror administrator.

## Reproducibility scope

The H2 demo above is the complete bundled quantitative test: it specifies the input geometry, basis, grid, optimized parameter file, dispersion setting, command, expected energy, tolerance, runtime, and tested software environment.

The repository does not include the datasets, preprocessing, fitting workflow, random seeds, or scripts needed to reproduce every table and figure in the referenced CF22D publication. Do not treat the H2 smoke test as a reproduction of the paper's full results.

## File structure

```text
.
├── CF22D_optimized_example.py
├── Parameters
├── dfthub_g16_builder.py
├── LICENSE
└── README.md
```

## Reference

Y. Liu, C. Zhang, Z. Liu, D. G. Truhlar, Y. Wang, X. He, "Supervised Learning of a Chemistry Functional with Damped Dispersion", *Nature Computational Science*, 2023, 3, 48–58.

## License

The original code and `Parameters` file in this repository are made available under the MIT License. The full license text is provided in `LICENSE`. Gaussian 16 source code, Gaussian binaries, and third-party dependencies are not covered by this repository's license and remain subject to their respective terms.
