# Offline deployment

## Preparing Python

A dedicated CPython 3.12 venv is recommended; current patch releases of 3.10/3.11 are also supported. Conda users can set up `conda/environment.yml` and then run `conda/install-release.sh`. Do not copy absolute paths or site-packages from an old server to a new machine.

- Ubuntu 22.04+ x86_64: install the chosen Python version, the matching venv support, and the system C runtime libraries. For offline machines, prepare the installation media in advance with the distribution's package manager.
- macOS Apple Silicon: install an arm64 Python 3.10–3.12 and avoid Rosetta x86_64 interpreters; v0.1.1 requires compiling the latest DFT engine following the build-from-source steps.
- Conda: on a networked machine, first run `conda create -n dfthub python=3.12 pip`, or prepare offline conda packages for the same architecture in advance; the DFThub wheelhouse does not include Python.

The Linux Release offline bundle names include the architecture and `cp310/cp311/cp312`. After extracting, run:

```bash
DFTHUB_INSTALL_PYTHON=python3.12 bash deploy/install-offline.sh /opt/dfthub/.venv
/opt/dfthub/.venv/bin/dfthub doctor --strict
/opt/dfthub/.venv/bin/dfthub serve --data-dir /var/lib/dfthub/data
```

The installer first verifies the platform and SHA256SUMS, then installs all dependencies with `--no-index --require-hashes`. If no matching wheel exists, it fails explicitly rather than attempting to compile or fetch upstream PySCF on an offline machine. All scientific libraries, static pages, and Swagger UI assets are included in the release bundle. The Conda installation path uses the same wheelhouse and does not install upstream `pyscf` from Conda/PyPI; macOS uses the build-from-source path.

## Configuration, paths, and migration

Copy `dfthub.env.example` to a location outside the repository, run `chmod 600` on it, and set `DFTHUB_ENV_FILE`. The file is loaded before the API configuration is imported; variables already set in the process environment take precedence over it, and the command-line options `--data-dir/--python` take precedence over both.

| Setting | Default / purpose |
|---|---|
| DFTHUB_DATA_DIR | `dfthub` under the XDG data home; accounts, jobs, templates, checkpoints |
| DFTHUB_PYTHON | The current interpreter; a separate compute environment must also have DFThub and the DFT engine installed |
| DFTHUB_TMB11_DIR | Read-only optimizer resources inside the package |
| DFTHUB_DEMO_ROOT | `optimizer` under the data directory; writable temporary optimization directory |
| DFTHUB_SCHEDULER_DIR | `scheduler` under the data directory |
| DFTHUB_AME418_ROOT | External AME418 initial calculation data; the minimal package does not include the large checkpoints |
| DFTHUB_MAIL_SUPPRESS | `1`; set explicitly to `0` when email is configured |
| DFTHUB_PUBLIC_URL | Access URL used in emails |
| DFTHUB_CPU_THREADS / DFTHUB_MEMORY_MB | CPU/memory reservation pool; auto-detected by default |
| DFTHUB_TASK_THREADS / DFTHUB_OPTIMIZER_THREADS | Maximum number of threads per task |

Migrating an existing server: stop the service and copy the entire old `dft_files` directory as the new data directory; copy any historical `demo_*` directories you want to restore separately into `DFTHUB_DEMO_ROOT`. The old Work/common/program copies are no longer used as program entry points; the release package uses its own pinned versions. Existing output, test_set, and input_srp directories are preserved as-is. Do not include working directories in a public release package.

For new forks and SCF snapshots, the geometry input directory is named `inputs/`, so that the default case-insensitive macOS file system does not treat an old `input/` directory and the `INPUT` descriptor file as the same name. The old layout can still be read on Linux. Before moving old Linux data to macOS, run `python tools/migrate_data_layout.py --data-dir /backup/dft_files` on a backup copy taken on Linux while the service is stopped to review the list of changes, then add `--apply` to rename the directories, and only then transfer the whole copy. Do not copy data with case conflicts to macOS first.

The service listens on 127.0.0.1:8188 by default. To expose it externally, use nginx/Caddy to forward the entire site; the API and frontend share the same origin. HTTPS is handled by the reverse proxy; set `DFTHUB_ENABLE_HSTS=1` only when serving over HTTPS. Start `dfthub serve` with a process manager, and do not use multiple WSGI processes sharing one in-memory queue. The CLI locks the data directory to prevent two instances from running.

## Building the engine from pinned source

On a networked build machine, prepare `build wheel setuptools cmake<4` for Python. Linux additionally requires a C/C++ compiler, the OpenBLAS development libraries, auditwheel, and patchelf; macOS arm64 requires the Xcode command-line tools, Homebrew llvm/libomp/openblas, and delocate.

```bash
git clone --branch DFT https://github.com/chen-yu-hao/pyscf.git .build/pyscf
# Alternatively, use git@github.com:chen-yu-hao/pyscf.git
git -C .build/pyscf checkout e7cb735789293acf461f8ebbb4ac6a08b68ba5d6
python tools/build_engine.py --source .build/pyscf --output dist/engine
python -m build
python tools/offline_bundle.py --engine dist/engine/dfthub_pyscf_dft-*.whl --package dist/dfthub-0.1.1-py3-none-any.whl
```

See `.github/workflows/release.yml` for the macOS LLVM/OpenBLAS flags and the complete build process; set `CMAKE_OSX_ARCHITECTURES=arm64` and `_PYTHON_HOST_PLATFORM=macosx-14.0-arm64`, and point `DFTHUB_MACOS_LIBOMP` to Homebrew's libomp.dylib. When repairing the wheel, unify the OpenMP shared library references to avoid conflicts between identically named libraries under different Homebrew prefixes. The engine source archive is also kept as a Release asset. A fallback source build requires the LibXC/libcint/XCFun sources and a toolchain; offline installation uses the prebuilt wheelhouse and needs no compiler. Do not enable `-march=native`, so that the release package is not tied to the build machine's instruction set.
The build script records the source archive and provenance of the latest DFT commit `e7cb735789293acf461f8ebbb4ac6a08b68ba5d6`; do not use the old `v0.1.0` wheel in place of this build.
