# Conda 安装

DFThub 的网页/API 和固定 PySCF DFT 引擎以 wheel 形式发布；Conda 负责准备 Python、NumPy/SciPy、BLAS 和系统运行库，避免把自定义二进制引擎误解析为 PyPI 上游 `pyscf`。

在线准备环境：

```bash
conda env create -f conda/environment.yml
conda activate dfthub-0.1.1
```

然后从对应 GitHub Release 的离线包安装：

```bash
bash conda/install-release.sh /path/to/dfthub-0.1.1-linux-x86_64-cp312
conda activate dfthub-0.1.1
dfthub doctor --strict
dfthub serve --data-dir ./dfthub-data
```

`conda/install-release.sh` 使用 release wheelhouse 和 `requirements.lock`，不访问 PyPI。`DFTHUB_CONDA_ENV` 可改环境名。v0.1.1 预编译离线包是 Linux x86_64；Apple Silicon 请使用 Conda 环境后按部署文档从最新 DFT 源码构建引擎。

如果只使用联网 Conda 环境，也可以先执行 `conda env create -f conda/environment.yml`，再从 Release 下载并解压 wheelhouse，执行：

```bash
python -m pip install --no-index --find-links ./wheelhouse dfthub
```

不要执行 `conda install pyscf` 或 `pip install pyscf`；DFThub 要求 `dfthub-pyscf-dft==2.14.0+dfthub.e7cb7357`，由 `dfthub doctor --strict` 检查实际导入的分支和提交。
