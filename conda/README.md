# Conda installation

DFThub's web interface/API and the pinned PySCF DFT engine are distributed as wheels. Conda prepares Python, NumPy/SciPy, BLAS, and the system runtime libraries, which prevents the custom binary engine from being resolved as upstream `pyscf` from PyPI.

Prepare the environment online:

```bash
conda env create -f conda/environment.yml
conda activate dfthub-0.1.1
```

Then install from the offline bundle of the corresponding GitHub Release:

```bash
bash conda/install-release.sh /path/to/dfthub-0.1.1-linux-x86_64-cp312
conda activate dfthub-0.1.1
dfthub doctor --strict
dfthub serve --data-dir ./dfthub-data
```

`conda/install-release.sh` uses the release wheelhouse and `requirements.lock` and does not access PyPI. Set `DFTHUB_CONDA_ENV` to change the environment name. The v0.1.1 prebuilt offline bundle is for Linux x86_64; on Apple Silicon, set up the Conda environment and then build the engine from the latest DFT source as described in the deployment guide.

If you only use an online Conda environment, you can also run `conda env create -f conda/environment.yml` first, then download and extract the wheelhouse from the Release and run:

```bash
python -m pip install --no-index --find-links ./wheelhouse dfthub
```

Do not run `conda install pyscf` or `pip install pyscf`. DFThub requires `dfthub-pyscf-dft==2.14.0+dfthub.e7cb7357`, and `dfthub doctor --strict` checks the branch and commit that are actually imported.
