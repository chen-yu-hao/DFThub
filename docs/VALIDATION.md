# Release validation

The Linux CPython 3.12 installation was validated in a fresh virtual environment
using only the release wheelhouse (`--no-index --require-hashes`). `pip check`
reported no broken requirements. Package directories were made read-only before
running an actual train/test fit from a separate writable data directory.

Release `v0.1.1` uses the latest `chen-yu-hao/pyscf` `DFT` commit
`e7cb735789293acf461f8ebbb4ac6a08b68ba5d6`, including the reviewed DFT/ERI/NUMA
changes. The engine wheel records this commit, its native library hashes, and
the `threadpoolctl` dependency in `pyscf/dfthub-provenance.json`.

- 93 Python regression checks cover API authentication, cancellation/deletion,
  status reporting, checkpoint chains, optional-test inheritance, partial-test
  failure, installed pages, process admission, and read-only resources.
- Four frontend regression suites and the TypeScript/production build pass.
- Six pages, including Swagger UI, render in Chromium with all external requests
  blocked and no JavaScript errors.
- Real CF22D RKS H2 and UKS H checks pass: 59 parameters, 62 descriptors,
  checkpoint round-trip, Newton/stability where orbital rotations exist, and
  completed-checkpoint reuse without recomputation.
- The bundled NumPy 2.2.6 / SciPy 1.15.3 / pandas 2.3.3 combination completes the
  small H2 reaction train/test fit (197 optimizer iterations on the local test).
  The same release fixture failed with newer NumPy/SciPy combinations; those
  failed runs were retained in the local validation logs and are not accepted
  deployment configurations. No production optimizer algorithm was changed.
- The fresh v0.1.1 offline wheelhouse installs `dfthub-pyscf-dft==2.14.0+dfthub.e7cb7357`,
  includes the Conda environment recipe, and passes `dfthub doctor --strict` with
  the latest DFT commit and new `pyscf.dft.numa` / `pyscf.scf.eri_cache` modules.

The published Linux release is gated on GitHub Actions targets for Python 3.10,
3.11 and 3.12. Each target runs offline installation, actual engine provenance
checks, API/pipeline tests, RKS/UKS science checks, and the complete train/test
fit before assets publish. macOS arm64 uses the documented source-build path;
its hosted runner was unavailable during this release window.

User uploads, existing job results, credentials, and old-server working trees
are not included. The original GitHub main branch remains unchanged.
