# Changelog

## v0.1.2

Same DFT engine as v0.1.1: `dfthub-pyscf-dft==2.14.0+dfthub.e7cb7357`
(`chen-yu-hao/pyscf` `DFT` commit `e7cb7357`). NumPy, SciPy and pandas pins are
unchanged.

### Added

- Command-line tools that read a DFThub `Parameters` file or a raw 59-value
  coefficient file without starting the service:
  `dfthub params check|show`, `dfthub export {pyscf,gaussian,orca,psi4}`
  (with `--no-d3`), `dfthub g16 build` (with `--dry-run`) and
  `dfthub pyscf demo`.
- `dfthub ps` and `dfthub kill` to list and stop running background
  calculations.
- `dfthub.functional`: one key-based reader/writer for CF22D parameters, the
  LibXC CF22D parameter mapping and the D3(0) parameters, shared by the
  pipeline and the PySCF, Gaussian 16, ORCA and Psi4 exports.
  `dfthub_g16_builder.py` and `CF22D_optimized_example.py` are kept as
  wrappers around it.
- Tests for parameter I/O, Gaussian patching, the four exports (golden
  files with and without D3) and the CLI, and `.ref` parser tests.
- Documentation: English README with install, command-line tools and
  per-program validation table; `docs/GAUSSIAN.md`, `docs/PROGRAMS.md`;
  public deployment behind a reverse proxy; mail and privacy settings.

### Fixed

- `total_mue` parsing; the `.ref` reference-file parser accepts the general
  format described in the upload template, and the template was updated.
- OpenBLAS on AVX-512 x86_64 Linux: `OPENBLAS_CORETYPE` is set to `Haswell`
  unless already defined.
- D3 dispersion falls back to the `dftd3` package when `pyscf-dispersion` is
  not available.
- Workspace DFT energy submission; `.zip` structure archives are accepted in
  the new-job form; the Guide shows a `.ref` example.
- The offline installer detects the bundle's Python version, and the offline
  source build works from the bundle wheelhouse.
- The environment file is loaded in one place with clear errors; mail
  settings are validated at startup (port range, TLS/SSL) and `dfthub serve`
  reports the mail status without printing credentials.

## v0.1.1

First portable release: offline Linux x86_64 bundles for Python 3.10–3.12
with the pinned PySCF DFT engine `e7cb7357`, and a Conda recipe. See
`docs/VALIDATION.md`.
