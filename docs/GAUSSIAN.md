# Gaussian 16 with DFThub parameters

Gaussian cannot read the 58 CF22D coefficients at run time. `dfthub g16 build` writes them, together with the exact-exchange fraction, into a licensed Gaussian 16 source tree and rebuilds it. This path is only for users who are licensed and equipped to compile Gaussian 16; Gaussian source code and binaries are not distributed by DFThub.

## Requirements

- Linux with `/bin/bash`, and DFThub installed (the command does not need the PySCF engine);
- a valid Gaussian 16 license;
- a compatible, licensed Gaussian 16 source tree containing `bsd/g16.profile` and `bsd/bldg16`;
- the compilers, build tools, memory and disk space required by that Gaussian 16 source distribution.

## Build

Put the parameter file and the source tree side by side:

```text
.
├── Parameters
└── g16/
    ├── bsd/g16.profile
    ├── bsd/bldg16
    └── ...
```

If `g16/` is absent, the command extracts the first archive it finds next to it, in this order: `g16.tar.gz`, then `CF22Dg16.tar.gz` (use `--archive PATH`, repeatable, to name others). It does not fall back to the next archive if extracting the first one fails. Use only a trusted archive that you are licensed to possess.

Make a separate backup of the clean source tree. Then check the parameter file and the source tree without modifying anything:

```bash
dfthub g16 build --source ./g16 --parameters Parameters --dry-run
```

The dry run reports where each parameter block was found and how many lines would change. Then patch and build:

```bash
dfthub g16 build --source ./g16 --parameters Parameters
```

The command:

1. reads the 58 CF22D coefficients and the HF value from `Parameters`, matching them by key name;
2. locates the CF22D source blocks in `utilnz.F` (deck `N12xP`, `IFunc.eq.6`: 40 `Cx`) and `utilam.F` (`IFunc.eq.36`: 9 `Cy`; `IFunc.eq.37`: 9 `Cz`; `IMOpt.eq.-25`: `IMHF`), in `g16/` or a nested `g16/g16/` layout;
3. patches those lines in place;
4. sources `bsd/g16.profile` and runs `./bsd/bldg16`;
5. after a successful build, removes any existing `g16-opt/` and moves the top-level `g16/` directory to `g16-opt/` (`--output DIR` selects another destination).

Each coefficient is written with 14 digits after the decimal point in scientific notation, and the HF fraction is rounded to the nearest `1e-6` for `IMHF`. The Gaussian source may therefore contain slightly rounded values rather than every digit read by the PySCF path.

Important behavior:

- All blocks are located and checked before any file is written; if a block is missing or ambiguous, or a value cannot be parsed or is missing, the command stops without patching anything.
- A later compiler failure does not roll back the patched source files. Restore the clean backup before retrying.
- An existing `g16-opt/` is deleted only after the new build succeeds, immediately before the move.
- The source root must be a directory named `g16`, because `g16root` and `GAUSS_EXEDIR` are derived from it.

The build time was not benchmarked; it depends on the source release, compiler toolchain, processor, memory and storage.

## Running the patched build

The patched blocks are the MN15 slots, so the rebuilt Gaussian runs the DFThub parameters through the `MN15` keyword. CF22D is parameterized together with D3 zero damping (s6 = 1.0, s8 = 0.0, sr6 = 1.53, no three-body term), which Gaussian accepts as GD3 IOps (a value of `-1` encodes zero):

```bash
dfthub export gaussian Parameters -o cf22d.gjf
```

```text
%Chk=cf22d.chk
#P MN15/def2QZVP
EmpiricalDispersion=GD3 IOp(3/174=1000000,3/175=-1,3/176=1530000)

CF22D, DFThub parameters sha256 ..., HF=...
...
```

Use `--keyword` if your patched build selects the slot under another name, `--basis` for another basis set and `--no-d3` to leave out dispersion. Replace the H2 geometry with your molecule.

**An unpatched Gaussian silently runs the original MN15 with this input.** Run it only with the `g16-opt` build, and check that the build directory you run is the patched one.

## Previous script

`python3 dfthub_g16_builder.py [--parameters PATH] [--dry-run]` still works and is equivalent to the command above with paths relative to the script (`./Parameters`, `./g16`, `./g16.tar.gz`, `./CF22Dg16.tar.gz`, `./g16-opt`). It is deprecated and will be removed in a later release.

## Troubleshooting

- **A source block is missing or ambiguous:** use the compatible clean source release expected by the builder; an already modified or different source version may not match.
- **The build fails after patching:** restore the clean backup before retrying with a corrected compiler or Gaussian build environment.
- **`Incomplete Parameters file`:** check that all 40 `Cx`, 9 `Cy`, 9 `Cz`, and one `HF` or `HF%` assignment are present (`dfthub params check Parameters`).

## Standalone PySCF example

`CF22D_optimized_example.py` in the repository root is the original standalone example; it now delegates to `dfthub.functional` from the checkout and still runs with upstream PySCF ≥ 2.13.1 outside the DFThub engine:

```bash
python CF22D_optimized_example.py                 # Parameters next to the script + D3
python CF22D_optimized_example.py --no-d3         # without D3 dispersion
python CF22D_optimized_example.py --original      # embedded original parameter set
python CF22D_optimized_example.py --parameters path/to/Parameters
```

It is equivalent to `dfthub pyscf demo`. The run ends with `Total energy: -1.1634860046 Hartree` (RKS H2, R = 0.74 Å, def2-QZVP, grid level 6). This value was reproduced with upstream PySCF 2.13.1/LibXC 7.0.0, PySCF 2.15.0/LibXC 7.1.2 on Python 3.14, and the DFThub engine (PySCF 2.14.0/LibXC 7.1.2). For this geometry the D3 term is only about −5 × 10⁻¹¹ Hartree, so `--no-d3` gives `converged SCF energy = -1.16348600457564`, which agrees within the `1e-8` Hartree tolerance.

Platform notes for upstream PySCF:

- **Python 3.10–3.13:** the tested pins were `numpy==2.1.3`, `scipy==1.15.3`, `h5py==3.12.1`, `pyscf==2.13.1`, `pyscf-dispersion==1.5.0`.
- **Python 3.14 and later:** those NumPy, SciPy and h5py pins have no binary wheels, so install current releases of `pyscf>=2.13.1` and `pyscf-dispersion`.
- **macOS:** `pyscf-dispersion` has no wheels, so D3 is unavailable; use `--no-d3` and `with_d3=False`. Untested.
- **Windows:** PySCF has no native Windows wheels; use WSL 2 and follow the Linux instructions.
- **With the DFThub engine:** install `pyscf-dispersion` with `--no-deps`, otherwise pip installs upstream `pyscf` next to `dfthub-pyscf-dft`.

If PySCF is older than 2.13.1, or if D3 is requested but `pyscf-dispersion` is not installed, the example stops before the SCF with a message explaining how to fix the environment.

The H2 demo is a smoke test, not a reproduction of the paper's results. Reference: Y. Liu, C. Zhang, Z. Liu, D. G. Truhlar, Y. Wang, X. He, "Supervised Learning of a Chemistry Functional with Damped Dispersion", *Nature Computational Science*, 2023, 3, 48–58.
