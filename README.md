# DFThub

DFThub 将 CF22D 参数拟合、训练/测试集评估、SCF 迭代和结果分析放在同一个网页中。Python wheel 内置静态前端；安装后不需要 Node.js、pnpm、PDM 或独立前端服务。

## 安装

使用 **CPython 3.10–3.12**，推荐 3.12；支持 **Linux x86_64（glibc 2.35+，例如 Ubuntu 22.04+）** 和 **macOS Apple Silicon arm64（macOS 14+）**。Windows 可使用符合上述 Linux 要求的 WSL2。

从 [GitHub Releases](https://github.com/chen-yu-hao/DFThub/releases/tag/v0.1.0) 下载与你的操作系统、CPU 和 Python 小版本匹配的离线包，解压后：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --no-index --find-links ./wheelhouse dfthub
# 或核对平台和所有 SHA256，并按锁文件安装：
DFTHUB_INSTALL_PYTHON=python3.12 bash deploy/install-offline.sh .venv

dfthub doctor --strict
dfthub serve --data-dir ./dfthub-data
```

打开 **http://127.0.0.1:8188**。Workspace、Analyze、Guide、Energy 和 API 文档均由此服务提供，页面运行不请求 CDN。离线包不含 Python 解释器，需先在目标机准备 Python 和 venv；Ubuntu 可用系统 python3/venv，macOS 可用 Python.org universal2 安装器并以 arm64 运行。Conda 用户可 `conda create -n dfthub python=3.12 pip`，再在该环境执行相同 pip 命令；隔离包须在联网机提前下载。

本次发布位置是 GitHub Release，不是 PyPI。普通 `pip install dfthub` 只有在指定本发布的 wheelhouse 后才是本项目。不要从未知同名索引包安装。源码安装也需先准备匹配的引擎 wheel：

```bash
git clone --branch release/0.1.0 https://github.com/chen-yu-hao/DFThub.git
cd DFThub
python -m pip install --find-links /path/to/wheelhouse .
```

## PySCF DFT 引擎

必须使用 `chen-yu-hao/pyscf` 的 **DFT** 分支固定提交
`72e5b26c91964acbf3186c5348f77a0f7faf44dd`，不是 DFT-combined，也不是上游 PyPI `pyscf`。

数值依赖固定为 NumPy 2.2.6、SciPy 1.15.3、pandas 2.3.3，并用完整训练/测试拟合验证。

分发名为 `dfthub-pyscf-dft==2.14.0+dfthub.72e5b26c`，Python 导入名仍为 `pyscf`。它包含 PySCF 2.14.0、LibXC 7.1.2、libcint 6.2.0 和固定 XCFun。`dfthub doctor --strict` 核对提交、代码/动态库 SHA256、LibXC 和 CF22D 可用性；服务启动前也进行此检查。不要在同一环境安装上游 `pyscf`，pip 不会识别两个分发包共享模块的冲突。

已有独立计算环境可用 `DFTHUB_PYTHON=/path/to/python`，该环境也必须安装本 DFThub wheel 和配套引擎。无需复制整个 conda 环境。

## 数据和部署

默认数据目录为 `$XDG_DATA_HOME/dfthub`，未设置时是 `~/.local/share/dfthub`。生产环境可指定：

```bash
dfthub serve --host 127.0.0.1 --port 8188 --data-dir /var/lib/dfthub/data
```

先由管理员创建目录并授权服务账户写入。上传文件、账号数据库、JWT 密钥、队列状态和结果均写入该目录，安装包可以只读。一个数据目录只允许一个服务进程。升级前停止该实例并备份整个数据目录；新版本不会覆盖既有任务和检查点。

环境变量与命令行、离线安装、迁移、反向代理和源代码构建见 [部署说明](deploy/README.md)。邮件默认关闭；配置 SMTP 后显式启用。不要将真实 `.env`、认证库、用户任务或密钥加入 Git。

调度器按可用 CPU、内存预算和基组 AO 数分配资源，支持 Linux 和 macOS，无 systemd 依赖。内存预算是预约和 PySCF 工作内存提示，不是系统级 RSS 限制。SCF 没有墙钟超时，保留分阶段检查点；测试集失败不会阻止已验证训练集进入下一轮 refine。

必需的 CF22D 拟合描述符、参考数据和默认权重包含在包内。AME418 的大型初始检查点不属于最小发布，需要通过 `DFTHUB_AME418_ROOT` 单独提供；普通用户数据集的拟合、SCF、参数导出及测试集不依赖它。

## 开发和验证

```bash
# 仅重新构建前端时需要 Node >=22 和 pnpm 11.5.3
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

回归覆盖认证、删除/取消、运行状态、测试集继承、训练集成功而测试集失败、检查点复用。CI 对 Linux x86_64 和 macOS arm64 的 Python 3.10/3.11/3.12 分别验证安装、页面和真实 RKS/UKS 科学 smoke，全部成功才发布资产。

原仓库 Gaussian 参数导出工具与说明保留于 [Gaussian 文档](docs/GAUSSIAN.md)。
