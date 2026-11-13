# Using DFThub parameters in PySCF, Gaussian, ORCA and Psi4

`dfthub export PROGRAM PARAMS` writes an input that applies one CF22D parameter set. `PARAMS` is a DFThub `Parameters` file or a raw 59-value coefficient file (`NEW-params.txt`). Every export records the parameter set's SHA-256 (of the 59 little-endian float64 values, as used by the DFThub pipeline), so an input can be traced back to its run.

## The parameter set

| DFThub key | Count | LibXC component | LibXC external parameters |
| --- | --- | --- | --- |
| `Cx(i,j,k)` | 40 | `HYB_MGGA_X_CF22D` (id 340) | `_CC000` … `_CC302` (same i, j, k) |
| `HF%` or `HF` | 1 | `HYB_MGGA_X_CF22D` | `_ax` (exact-exchange fraction) |
| `Cy(n)` | 9 | `MGGA_C_CF22D` (id 341) | `_a0` … `_a8` (`_a9` … `_a11` are 0) |
| `Cz(n)` | 9 | `MGGA_C_CF22D` | `_b0` … `_b8` (`_b9` … `_b11` are 0) |

CF22D is in LibXC since 7.0.0. In LibXC the exact-exchange parameter `_ax` only sets the hybrid coefficient; the semilocal part does not depend on it, so each program must add exact exchange with exactly this fraction.

CF22D is fitted together with Grimme D3 zero damping without the three-body term: s6 = 1.0, s8 = 0.0, rs6 (sr6) = 1.53, rs8 = 1.0, α6 = 14. This equals PySCF's `d3zero:cf22d` and the DFThub pipeline's `dftd3` call. `--no-d3` leaves it out.

`dfthub params show Parameters` prints each value with its LibXC name; `dfthub params check Parameters` validates a file. The reader accepts arbitrary whitespace, case-insensitive keys, `#` comments, `E` or Fortran `D` exponents and any order; unknown keys are ignored and a repeated key keeps its last value.

## PySCF

```bash
dfthub export pyscf Parameters -o CF22D_optimized.py
python CF22D_optimized.py            # H2 demo; --no-d3 without dispersion
```

The script is self-contained (NumPy and PySCF ≥ 2.13.1) and is built from the same template as the "PySCF functional (.py)" file the web application offers for a run. Use it in your own calculation:

```python
from pyscf import dft, gto
from CF22D_optimized import register_cf22d

mol = gto.M(atom="H 0 0 0; H 0 0 0.74", basis="def2-qzvp")
mf = dft.RKS(mol)          # or dft.UKS
mf.grids.level = 6
register_cf22d(mf)         # functional + D3(0); register_cf22d(mf, with_d3=False) without it
mf.kernel()
```

`register_cf22d_srp(mf)` sets only the functional and leaves `mf.disp` unchanged; the DFThub pipeline uses it and adds D3 itself. Inside a DFThub installation the same is available as `dfthub.functional.pyscf.register_cf22d(mf, "Parameters")`, and `dfthub pyscf demo` runs the H2 check (`Total energy: -1.1634860046 Hartree` with the bundled `Parameters`).

D3 needs `pyscf-dispersion`. With the DFThub engine install it with `python -m pip install --no-deps pyscf-dispersion`, so pip does not add upstream `pyscf`.

## Gaussian 16

Gaussian needs a rebuilt binary; see [GAUSSIAN.md](GAUSSIAN.md). `dfthub export gaussian` writes a `.gjf` template for that build (`MN15` keyword, GD3 IOps for the D3 parameters).

## ORCA

```bash
dfthub export orca Parameters -o cf22d.inp
orca cf22d.inp > cf22d.out
```

The input selects the LibXC components in `%method` and sets every external parameter (ORCA ≥ 5.1):

```text
! RKS def2-QZVP DefGrid3 D3ZERO

%method
  Method      DFT
  Exchange    hyb_mgga_x_cf22d
  Correlation mgga_c_cf22d
  ExtParamX "_CC000" -1.8691297464873982e-01
  ...                                      # 41 ExtParamX and 24 ExtParamC lines
  ScalHFX     5.8103542452473211e-01  # exact exchange
  ScalDFX     1.0
  ScalGGAC    1.0
  ScalLDAC    1.0
  D3S6     1.0
  D3RS6    1.53
  D3S8     0.0
  D3alpha6 14
end
```

Requirements and checks:

- ORCA must be linked against LibXC ≥ 7.0. The LibXC version is printed at the top of the output; `orca -libxcinfo hyb_mgga_x_cf22d` must list the functional.
- Confirm in the first output that ORCA reports the modified external parameters and an exact-exchange fraction equal to the `HF` value. `ScalHFX` and the unit `Scal*` values are given explicitly as a safeguard.
- This input has not been run in ORCA by DFThub's tests. Before production use, compare one energy with the PySCF export for the same geometry, basis and grid.

## Psi4

```bash
dfthub export psi4 Parameters -o cf22d_psi4.py
python cf22d_psi4.py                 # or: psi4 cf22d_psi4.py
```

The file defines a custom functional dictionary and calls `psi4.energy("scf", dft_functional=CF22D_DFTHUB)`:

```python
CF22D_DFTHUB = {
    "name": "CF22D-DFTHUB",
    "x_functionals": {"HYB_MGGA_X_CF22D": {"use_libxc": False, "tweak": {"_CC000": ..., "_ax": ...}}},
    "x_hf": {"alpha": 0.5810354245247321},
    "c_functionals": {"MGGA_C_CF22D": {"tweak": {"_a0": ..., "_b0": ...}}},
    "dispersion": {"type": "d3zero2b",
                   "params": {"s6": 1.0, "s8": 0.0, "sr6": 1.53, "sr8": 1.0, "alpha6": 14.0}},
}
```

- `"use_libxc": False` with an explicit `"x_hf"` is required: Psi4 reads a LibXC hybrid coefficient before it applies tweaks, so relying on LibXC would keep the default 0.462806. Psi4 prints a warning that the manual `x_hf` value is used; that is expected.
- Psi4 must be linked against LibXC ≥ 7.0, and `d3zero2b` needs a D3 engine (`s-dftd3` or `dftd3`) available to Psi4.
- This input has not been run in Psi4 by DFThub's tests. Compare one energy with the PySCF export before production use; the example uses a (99, 590) integration grid, so adjust the grid options to match your PySCF settings.
