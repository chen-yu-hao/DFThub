# DFThub

DFThub example repository for using optimized density-functional parameters in PySCF and Gaussian 16.

## Contents

- `CF22D_optimized_example.py`: CF22D parameter registration example for PySCF/libxc, including `Parameters` loading and CF22D D3 zero-damping dispersion.
- `dfthub_g16_builder.py`: patches Gaussian 16 source files with values from `Parameters`, builds Gaussian 16, and writes the result as `g16-opt`.
- `Parameters`: DFThub-style parameter file containing `Cx`, `HF%`, `Cy`, and `Cz` values.

## Clone

```bash
git clone https://github.com/chen-yu-hao/DFThub.git
cd DFThub
```

## PySCF Example

Requirements:

- Python 3
- NumPy
- PySCF >= 2.13.1
- pyscf-dispersion
- A libxc/PySCF build that supports CF22D

Install dependencies:

```bash
pip install numpy pyscf pyscf-dispersion
```

Run the example:

```bash
python CF22D_optimized_example.py
```

Use the functional in another PySCF script:

```python
from pyscf import gto, dft
from CF22D_optimized_example import register_cf22d

mol = gto.M(atom="H 0 0 0; H 0 0 0.74", basis="def2-qzvp")
mf = dft.RKS(mol)
mf.grids.level = 6

register_cf22d(mf)
mf.kernel()

print(mf.e_tot)
```

By default, `register_cf22d(mf)` reads the repository `Parameters` file and enables D3 zero-damping dispersion with PySCF's official `cf22d` D3 parameter set. To use the embedded CF22D parameters without D3:

```python
register_cf22d(mf, parameters_path=None, with_d3=False)
```

## Gaussian 16 Builder

`dfthub_g16_builder.py` reads `./Parameters`, patches Gaussian 16 source files, runs the Gaussian build script, and renames the completed source/build directory to `g16-opt`.

Expected layout:

```text
.
├── Parameters
├── dfthub_g16_builder.py
└── g16/
```

If `g16/` is not present, the script tries to extract `g16.tar.gz` or `CF22Dg16.tar.gz` from the current directory.

Run:

```bash
python3 dfthub_g16_builder.py
```

Important behavior:

- The script modifies `g16/utilnz.F` and `g16/utilam.F`.
- Patch positions are found by source blocks, not fixed line numbers.
- If an expected block is missing or ambiguous, the script stops before writing changes.
- After a successful build, existing `g16-opt/` is removed and `g16/` is renamed to `g16-opt/`.

## File Structure

```text
.
├── CF22D_optimized_example.py
├── Parameters
├── dfthub_g16_builder.py
└── README.md
```

## Reference

Y. Liu, C. Zhang, Z. Liu, D. G. Truhlar, Y. Wang, X. He, "Supervised Learning of a Chemistry Functional with Damped Dispersion", *Nature Computational Science*, 2023, 3, 48-58.

## License

This project is licensed under the MIT License. See `LICENSE` for details.
