# DFThub

DFThub brings CF22D parameter fitting, training/test set evaluation, SCF iterations, and result analysis together in a single web interface. The Python wheel ships with a prebuilt static frontend, so after installation you do not need Node.js, pnpm, PDM, or a separate frontend server.

## Installation

Use **CPython 3.10–3.12** (3.12 recommended). v0.1.1 provides prebuilt packages for **Linux x86_64 (glibc 2.35+, e.g. Ubuntu 22.04+)**. On macOS Apple Silicon, use the Conda environment and build from the latest DFT source; on Windows, use WSL2 with a distribution that meets the Linux requirements.

Download the offline bundle matching your operating system, CPU, and Python minor version from [GitHub Releases](https://github.com/chen-yu-hao/DFThub/releases/tag/v0.1.1), extract it, and then run:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --no-index --find-links ./wheelhouse dfthub
# Or verify the platform and all SHA256 checksums, and install from the lock file:
DFTHUB_INSTALL_PYTHON=python3.12 bash deploy/install-offline.sh .venv

dfthub doctor --strict
dfthub serve --data-dir ./dfthub-data
```

Open **http://127.0.0.1:8188**. The Workspace, Analyze, Guide, and Energy pages and the API documentation are all served by this process, and the pages make no CDN requests at runtime. The offline bundle does not include a Python interpreter, so prepare Python and venv on the target machine first: on Ubuntu, use the system python3/venv; on macOS, use the Python.org universal2 installer and run it as arm64. Conda users can run `conda create -n dfthub python=3.12 pip` and then run the same pip commands inside that environment; for air-gapped machines, the packages must be downloaded in advance on a networked machine.

This release is distributed through GitHub Releases, not PyPI. A plain `pip install dfthub` installs this project only when it points to this release's wheelhouse. Do not install a package with the same name from an unknown index. Installing from source also requires the matching engine wheel to be available first:

```bash
git clone --branch release/0.1.1 https://github.com/chen-yu-hao/DFThub.git
cd DFThub
python -m pip install --find-links /path/to/wheelhouse .
```

## PySCF DFT engine

DFThub requires the **DFT** branch of `chen-yu-hao/pyscf` at the pinned commit
`e7cb735789293acf461f8ebbb4ac6a08b68ba5d6`. This is neither the DFT-combined branch nor upstream `pyscf` from PyPI.

Numerical dependencies are pinned to NumPy 2.2.6, SciPy 1.15.3, pandas 2.3.3, and threadpoolctl 3.x, and have been validated with full training/test set fitting.

The distribution name is `dfthub-pyscf-dft==2.14.0+dfthub.e7cb7357`; the Python import name remains `pyscf`. It contains PySCF 2.14.0, LibXC 7.1.2, libcint 6.2.0, and a pinned XCFun. `dfthub doctor --strict` verifies the commit, the SHA256 checksums of the code and shared libraries, LibXC, and CF22D availability; the same check runs before the server starts. Do not install upstream `pyscf` in the same environment: pip does not detect the conflict between two distributions that share a module.

If you already have a separate compute environment, point to it with `DFTHUB_PYTHON=/path/to/python`; that environment must also have this DFThub wheel and the matching engine installed. There is no need to copy the entire conda environment.

### Conda

Conda prepares Python, BLAS, and the numerical libraries, while DFThub and the pinned PySCF DFT engine are still installed from the release wheelhouse:

```bash
conda env create -f conda/environment.yml
conda activate dfthub-0.1.1
bash conda/install-release.sh /path/to/dfthub-0.1.1-linux-x86_64-cp312
dfthub doctor --strict
```

No prebuilt engine wheel for macOS arm64 is published with v0.1.1; after setting up `conda/environment.yml`, build from the DFT source as described in the deployment guide. See the [Conda installation guide](conda/README.md) for details.

## Data and deployment

The default data directory is `$XDG_DATA_HOME/dfthub`, or `~/.local/share/dfthub` if that variable is unset. In production, specify it explicitly:

```bash
dfthub serve --host 127.0.0.1 --port 8188 --data-dir /var/lib/dfthub/data
```

An administrator should create this directory first and grant the service account write access to it. Uploaded files, the account database, JWT secrets, queue state, and results are all written to this directory, so the installed package can be read-only. Only one server process may use a data directory at a time. Before upgrading, stop the instance and back up the entire data directory; a new version does not overwrite existing jobs or checkpoints.

See the [deployment guide](deploy/README.md) for environment variables and command-line options, offline installation, migration, reverse proxies, and building from source. Email is disabled by default; enable it explicitly after configuring SMTP. Never commit a real `.env` file, authentication database, user jobs, or secrets to Git.

The scheduler allocates resources based on available CPUs, the memory budget, and the number of basis-set AOs. It supports Linux and macOS and does not depend on systemd. The memory budget is a reservation and a hint for PySCF working memory, not a system-level RSS limit. SCF has no wall-clock timeout and keeps staged checkpoints; a test set failure does not prevent a validated training set from proceeding to the next refine round.

The CF22D fitting descriptors, reference data, and default weights required for fitting are included in the package. The large AME418 initial checkpoints are not part of the minimal release and must be supplied separately via `DFTHUB_AME418_ROOT`; fitting, SCF, parameter export, and test sets for ordinary user datasets do not depend on them.

## Development and testing

```bash
# Node >=22 and pnpm 11.5.3 are only needed to rebuild the frontend
cd Client/DFThub
pnpm install --frozen-lockfile
pnpm run build
cd ../..
python tools/sync_frontend.py
python -m pip install build
python -m build
python tools/run_tests.py
python tools/scientific_smoke.py
```

Regression tests cover authentication, deletion/cancellation, run status, test set inheritance, the case where the training set succeeds but the test set fails, and checkpoint reuse. CI validates installation, the web pages, and real RKS/UKS scientific smoke tests on Linux x86_64 with Python 3.10/3.11/3.12; the macOS build-from-source path is documented in the deployment guide.

The Gaussian parameter export tool and instructions from the original repository are preserved in the [Gaussian documentation](docs/GAUSSIAN.md).
