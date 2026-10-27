# Release validation

The Linux CPython 3.12 installation was validated in a fresh virtual environment
using only the release wheelhouse (`--no-index --require-hashes`). `pip check`
reported no broken requirements. Package directories were made read-only before
running an actual train/test fit from a separate writable data directory.

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

The published release is additionally gated on all six GitHub Actions targets:
Linux x86_64 and macOS arm64, each with Python 3.10, 3.11 and 3.12. Each target
runs offline installation, actual engine provenance checks, API/pipeline tests,
RKS/UKS science checks, and the complete train/test fit before assets publish.
See the workflow run linked from the release commit for per-platform evidence.

User uploads, existing job results, credentials, and old-server working trees
are not included. The original GitHub main branch remains unchanged.
