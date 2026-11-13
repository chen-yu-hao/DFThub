# DFThub

DFThub brings CF22D parameter fitting, training- and test-set evaluation, SCF iterations and result analysis together in one web application. The Python wheel ships the static frontend, so no Node.js, pnpm, PDM or separate frontend service is needed after installation.

DFThub also includes command-line tools that read a DFThub `Parameters` file and apply the functional in PySCF, Gaussian 16, ORCA and Psi4 (see [Command-line tools](#command-line-tools)).

## Installation

Use **CPython 3.10–3.12**; 3.12 is recommended. v0.1.1 provides prebuilt packages for **Linux x86_64 (glibc 2.35+, e.g. Ubuntu 22.04+)**. On macOS Apple Silicon, use the Conda environment and build the latest DFT engine from source; on Windows, use WSL2 with a distribution that meets the Linux requirements.

Download the offline bundle that matches your operating system, CPU and Python minor version from [GitHub Releases](https://github.com/chen-yu-hao/DFThub/releases/tag/v0.1.1) (`cp310`, `cp311` or `cp312` for Python 3.10, 3.11 or 3.12). The `wheelhouse/` directory is inside the unpacked bundle, not in this Git repository, so run the install commands from the bundle directory. The complete sequence for Python 3.12:

```bash
# 1. Check the Python version (must be 3.10–3.12 and match the bundle)
python3.12 --version

# 2. Download and unpack the bundle in a directory of your choice (not inside the Git checkout)
curl -LO https://github.com/chen-yu-hao/DFThub/releases/download/v0.1.1/dfthub-0.1.1-linux-x86_64-cp312.tar.gz
tar xzf dfthub-0.1.1-linux-x86_64-cp312.tar.gz

# 3. Enter the bundle directory (it contains wheelhouse/, deploy/, conda/, requirements.lock)
cd dfthub-0.1.1-linux-x86_64-cp312

# 4. Create a clean virtual environment and install
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --no-index --find-links ./wheelhouse dfthub
# or verify the platform and every SHA256, then install from the lock file:
#   DFTHUB_INSTALL_PYTHON=python3.12 bash deploy/install-offline.sh .venv

# 5. Verify and start
dfthub doctor --strict
dfthub serve --data-dir ./dfthub-data
```

For Python 3.10 or 3.11, replace `cp312` and `python3.12` accordingly. If pip reports `Location './wheelhouse' is ignored` or `No matching distribution found for dfthub`, the current directory is not the unpacked bundle; `cd` into it first.

Open **http://127.0.0.1:8188**. Workspace, Analyze, Guide, Energy and the API documentation are all served from there, and the pages make no CDN requests. The offline bundle does not contain a Python interpreter: prepare Python and venv on the target machine first. On Ubuntu use the system python3/venv; on macOS use the Python.org universal2 installer and run it as arm64. Conda users can run `conda create -n dfthub python=3.12 pip` and then the same pip commands inside that environment; for an isolated machine, download the bundle in advance on a connected one.

This release is published on GitHub Releases, not PyPI. A plain `pip install dfthub` refers to this project only when it points at this release's wheelhouse; do not install a same-named package from an unknown index.

A source install (needed for features newer than the published bundle, such as the [command-line tools](#command-line-tools)) uses the bundle's wheelhouse for the pinned engine. Replace `/path/to/dfthub-0.1.1-linux-x86_64-cp312` with the bundle directory unpacked in step 2:

```bash
git clone https://github.com/chen-yu-hao/DFThub.git
cd DFThub
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --find-links /path/to/dfthub-0.1.1-linux-x86_64-cp312/wheelhouse .
dfthub doctor --strict
```

Install into a clean environment: if `python -m pip show pyscf` finds upstream `pyscf`, it conflicts with the DFThub engine and `dfthub doctor --strict` reports an error.

## PySCF DFT engine

DFThub requires the **DFT** branch of `chen-yu-hao/pyscf` at the pinned commit
`e7cb735789293acf461f8ebbb4ac6a08b68ba5d6` — not DFT-combined and not upstream PyPI `pyscf`.

Numerical dependencies are pinned to NumPy 2.2.6, SciPy 1.15.3, pandas 2.3.3 and threadpoolctl 3.x, and were validated with complete training/test fits.

The distribution is named `dfthub-pyscf-dft==2.14.0+dfthub.e7cb7357`; its import name is still `pyscf`. It contains PySCF 2.14.0, LibXC 7.1.2, libcint 6.2.0 and a pinned XCFun. `dfthub doctor --strict` checks the commit, the SHA256 of code and shared libraries, LibXC and CF22D availability; the service runs the same check before it starts. Do not install upstream `pyscf` into the same environment: pip does not detect that two distributions share one module.

An existing, separate compute environment can be selected with `DFTHUB_PYTHON=/path/to/python`; that environment must also have this DFThub wheel and the matching engine installed. There is no need to copy a whole conda environment.

### Conda

Conda provides Python, BLAS and the numerical libraries; DFThub and the pinned PySCF DFT engine are still installed from the release wheelhouse:

```bash
conda env create -f conda/environment.yml
conda activate dfthub-0.1.1
bash conda/install-release.sh /path/to/dfthub-0.1.1-linux-x86_64-cp312   # the unpacked bundle directory
dfthub doctor --strict
```

No prebuilt macOS arm64 engine wheel is published with v0.1.1; after creating the environment from `conda/environment.yml`, build the engine from the DFT sources as described in the deployment guide. See the [Conda installation guide](conda/README.md).

## Command-line tools

These commands read a DFThub `Parameters` file (40 `Cx`, 9 `Cy`, 9 `Cz` and `HF%` or `HF`, matched by key name) or a raw 59-value coefficient file such as `NEW-params.txt`. They do not start the service and do not run the engine check; `params`, `export` and `g16` work without the PySCF engine.

```bash
dfthub params check Parameters                 # validate; --json for machine-readable output
dfthub params show Parameters                  # every coefficient with its LibXC name
dfthub export pyscf    Parameters -o CF22D_optimized.py
dfthub export gaussian Parameters -o cf22d.gjf
dfthub export orca     Parameters -o cf22d.inp
dfthub export psi4     Parameters -o cf22d_psi4.py
dfthub g16 build --source ./g16 --parameters Parameters --dry-run
dfthub pyscf demo --parameters Parameters      # H2 check; --original, --no-d3
```

Without `-o`, `export` writes to standard output. `--no-d3` leaves out the CF22D D3(0) dispersion correction (s6 = 1.0, s8 = 0.0, rs6 = 1.53, no three-body term); `--basis` changes the basis of the example input.

| Program | How the parameters are applied | Validation in this repository |
| --- | --- | --- |
| PySCF | LibXC external parameters of `HYB_MGGA_X_CF22D`/`MGGA_C_CF22D` and PySCF `d3zero:cf22d` | H2 reference energy reproduced with the DFThub engine |
| Gaussian 16 | Coefficients written into a licensed source tree (`dfthub g16 build`), then `MN15` with GD3 IOps in that build | Patching tested on synthetic sources; no Gaussian build was run |
| ORCA ≥ 5.1 | `ExtParamX`/`ExtParamC` for every LibXC parameter; needs ORCA linked to LibXC ≥ 7.0 | Input text tested; not run in ORCA |
| Psi4 | Custom functional dictionary with LibXC `tweak`s and explicit exact exchange; needs LibXC ≥ 7.0 | Input text tested; not run in Psi4 |

Details, including how to check the result in each program, are in [docs/PROGRAMS.md](docs/PROGRAMS.md) and, for Gaussian, [docs/GAUSSIAN.md](docs/GAUSSIAN.md). The root scripts `dfthub_g16_builder.py` and `CF22D_optimized_example.py` remain as deprecated wrappers around these commands.

## Data and deployment

The default data directory is `$XDG_DATA_HOME/dfthub`, or `~/.local/share/dfthub` when that is not set. A production deployment can name one:

```bash
dfthub serve --host 127.0.0.1 --port 8188 --data-dir /var/lib/dfthub/data
```

An administrator should create the directory first and grant the service account write access. Uploads, the account database, the JWT secret, queue state and results are all written there, so the installation itself can be read-only. Only one service process may use a data directory. Before upgrading, stop the instance and back up the whole data directory; a new version does not overwrite existing jobs or checkpoints.

### Public access

By default `dfthub serve` listens on **127.0.0.1:8188**, so only the machine itself can open the site. For access from other machines or the internet, keep DFThub on 127.0.0.1 and put a reverse proxy with HTTPS in front of it. The web pages and the API are served from the same origin, so one proxy rule covers the whole site. `--host 0.0.0.0` would expose the service directly over plain HTTP, sending passwords and login tokens unencrypted; use it only on a trusted private network.

**Before you go public:** registration is open. Anyone who can reach the site can create an account and submit compute jobs; there is no e-mail verification or rate limit. Restrict access at the proxy or firewall (for example an IP allowlist, HTTP basic auth or a VPN) if the server should not run calculations for strangers.

1. Create the data directory and an environment file outside the installation:

   ```bash
   sudo useradd --system --home /var/lib/dfthub --shell /usr/sbin/nologin dfthub
   sudo mkdir -p /var/lib/dfthub/data /etc/dfthub
   sudo chown -R dfthub:dfthub /var/lib/dfthub
   sudo cp deploy/dfthub.env.example /etc/dfthub/dfthub.env
   sudo chown dfthub:dfthub /etc/dfthub/dfthub.env
   sudo chmod 600 /etc/dfthub/dfthub.env
   ```

   In `/etc/dfthub/dfthub.env`, set at least:

   ```text
   DFTHUB_DATA_DIR=/var/lib/dfthub/data
   DFTHUB_PUBLIC_URL=https://dfthub.example.org
   DFTHUB_ENABLE_HSTS=1
   ```

   Set `DFTHUB_ENABLE_HSTS=1` only when the site is served over HTTPS. `DFTHUB_PUBLIC_URL` is the address used in e-mails.

2. Run DFThub on 127.0.0.1 under a process manager. With systemd (any process manager works; DFThub does not require systemd), create `/etc/systemd/system/dfthub.service`, adjusting the virtual-environment path:

   ```ini
   [Unit]
   Description=DFThub
   After=network.target

   [Service]
   User=dfthub
   Environment=DFTHUB_ENV_FILE=/etc/dfthub/dfthub.env
   ExecStart=/opt/dfthub/.venv/bin/dfthub serve --host 127.0.0.1 --port 8188
   Restart=on-failure

   [Install]
   WantedBy=multi-user.target
   ```

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now dfthub
   ```

   Run exactly one instance per data directory; do not start several WSGI workers that share the in-memory job queue.

3. Configure nginx as the reverse proxy, e.g. `/etc/nginx/sites-available/dfthub`:

   ```nginx
   server {
       listen 80;
       server_name dfthub.example.org;

       client_max_body_size 1g;   # nginx's 1 MB default rejects dataset uploads with 413

       location / {
           proxy_pass http://127.0.0.1:8188;
           proxy_http_version 1.1;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_read_timeout 600s;
           proxy_send_timeout 600s;
       }
   }
   ```

   ```bash
   sudo ln -s /etc/nginx/sites-available/dfthub /etc/nginx/sites-enabled/dfthub
   sudo nginx -t
   sudo systemctl reload nginx
   sudo certbot --nginx -d dfthub.example.org   # adds HTTPS on port 443 (Let's Encrypt)
   ```

4. Open only ports 80 and 443 in the firewall and keep 8188 closed, for example with ufw:

   ```bash
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw deny 8188/tcp
   ```

Then open `https://dfthub.example.org`. Replace `dfthub.example.org` with your domain; its DNS record must point to the server. More configuration options are listed in the [deployment guide](deploy/README.md).

Environment variables and command-line options, offline installation, migration, reverse proxies and source builds are described in the [deployment guide](deploy/README.md). Mail is off by default; enable it explicitly after configuring SMTP. Never add a real `.env`, the authentication database, user jobs or secrets to Git.

The scheduler allocates resources by available CPUs, memory budget and the number of basis-set AOs, supports Linux and macOS, and does not depend on systemd. The memory budget is a reservation and a PySCF working-memory hint, not a system-wide RSS limit. SCF has no wall-clock timeout and keeps staged checkpoints; a failing test set does not stop a validated training set from entering the next refinement round.

The CF22D fitting descriptors, reference data and default weights that DFThub needs are included in the package. The large initial AME418 checkpoints are not part of the minimal release and must be provided separately through `DFTHUB_AME418_ROOT`; fitting, SCF, parameter export and test sets for ordinary user datasets do not depend on them.

## Development and validation

```bash
# Node >= 22 and pnpm 11.5.3 are needed only to rebuild the frontend
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

The regression tests cover authentication, deletion/cancellation, run status, test-set inheritance, a successful training set with a failing test set, checkpoint reuse, and the parameter tools (`Parameters` I/O, Gaussian source patching, exports and the CLI). CI validates installation, pages and a real RKS/UKS scientific smoke test on Linux x86_64 with Python 3.10/3.11/3.12; the macOS source-build path is kept in the deployment guide.

## License

The original code and `Parameters` file in this repository are available under the MIT License; see `LICENSE` and `THIRD_PARTY.md`. Gaussian 16, ORCA and Psi4 are not distributed here and remain subject to their own licenses.
