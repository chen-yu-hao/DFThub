# 离线部署

## Python 准备

推荐独立 CPython 3.12 venv；也支持 3.10/3.11 的当前补丁版。不要把旧服务器绝对路径或 site-packages 复制到新机器。

- Ubuntu 22.04+ x86_64：安装所选版本 Python、对应 venv 支持和系统 C 运行库。离线机器需提前通过发行版包管理器准备安装介质。
- macOS 14+ Apple Silicon：安装 arm64 Python 3.10–3.12，避免 Rosetta x86_64 解释器。
- Conda：联网机先创建 `conda create -n dfthub python=3.12 pip`，或提前准备同架构离线 conda 包；DFThub wheelhouse 不携带 Python。

Release 离线包命名包含操作系统、架构和 `cp310/cp311/cp312`。解压后运行：

```bash
DFTHUB_INSTALL_PYTHON=python3.12 bash deploy/install-offline.sh /opt/dfthub/.venv
/opt/dfthub/.venv/bin/dfthub doctor --strict
/opt/dfthub/.venv/bin/dfthub serve --data-dir /var/lib/dfthub/data
```

安装器先验证平台和 SHA256SUMS，再用 `--no-index --require-hashes` 安装所有依赖。无匹配 wheel 时明确失败，不在断网机器上尝试编译或获取上游 PySCF。所有科学库、静态页面和 Swagger UI 资源都包含在发行包中。

## 配置、路径和迁移

复制 `dfthub.env.example` 到仓库之外，`chmod 600`，设置 `DFTHUB_ENV_FILE`。文件在导入 API 配置前加载；现有进程环境优先，命令行 `--data-dir/--python` 优先于两者。

| 配置 | 默认值/用途 |
|---|---|
| DFTHUB_DATA_DIR | XDG data home 下的 dfthub；账号、任务、模板、检查点 |
| DFTHUB_PYTHON | 当前解释器；独立计算环境也需安装 DFThub 和 DFT 引擎 |
| DFTHUB_TMB11_DIR | 包内只读 optimizer 资源 |
| DFTHUB_DEMO_ROOT | 数据目录下的 optimizer，可写临时优化目录 |
| DFTHUB_SCHEDULER_DIR | 数据目录下 scheduler |
| DFTHUB_AME418_ROOT | 外部 AME418 初始计算数据；最小包不含大型检查点 |
| DFTHUB_MAIL_SUPPRESS | 1；配置邮件时显式设为 0 |
| DFTHUB_PUBLIC_URL | 邮件中的访问地址 |
| DFTHUB_CPU_THREADS / DFTHUB_MEMORY_MB | CPU/内存预约池，默认自动探测 |
| DFTHUB_TASK_THREADS / DFTHUB_OPTIMIZER_THREADS | 每项任务的最大线程数 |

现有服务器迁移：停服务，复制整个旧 `dft_files` 为新数据目录；把需要恢复的历史 `demo_*` 单独复制到 `DFTHUB_DEMO_ROOT`。旧 Work/common/program 副本不再作为程序入口，发行包使用其自身固定版本。已有输出、test_set 和 input_srp 目录原样保留。不要把工作目录打进公开发布包。

服务默认监听 127.0.0.1:8188。对外服务可用 nginx/Caddy 转发整个站点；API 和前端同源。HTTPS 由反向代理管理，仅在 HTTPS 下设 `DFTHUB_ENABLE_HSTS=1`。用进程管理器启动 `dfthub serve`，不要用多个 WSGI 进程共享一个内存队列。CLI 锁定数据目录以避免双实例。

## 从固定源代码构建引擎

在联网构建机准备 Python 的 `build wheel setuptools cmake<4`；Linux 还需 C/C++ 编译器、OpenBLAS 开发库、auditwheel、patchelf；macOS arm64 需 Xcode command-line tools、Homebrew llvm/libomp/openblas 和 delocate。

```bash
git clone --branch DFT https://github.com/chen-yu-hao/pyscf.git .build/pyscf
# 也可使用 git@github.com:chen-yu-hao/pyscf.git
git -C .build/pyscf checkout 72e5b26c91964acbf3186c5348f77a0f7faf44dd
python tools/build_engine.py --source .build/pyscf --output dist/engine
python -m build
python tools/offline_bundle.py --engine dist/engine/dfthub_pyscf_dft-*.whl --package dist/dfthub-0.1.0-py3-none-any.whl
```

macOS 的 LLVM/OpenBLAS flags 与完整构建流程见 `.github/workflows/release.yml`；设置 `CMAKE_OSX_ARCHITECTURES=arm64`、`_PYTHON_HOST_PLATFORM=macosx-14.0-arm64` 及 `DFTHUB_MACOS_LIBOMP` 指向 Homebrew libomp.dylib。修复 wheel 时统一 OpenMP 动态库引用，避免不同 Homebrew 前缀的同名库冲突。引擎源码包也作为 Release 资产保存。源码回退构建需要获得 LibXC/libcint/XCFun 源码和工具链；离线安装使用预编译 wheelhouse，无需编译器。不要启用 `-march=native`，以免发行包绑定构建机指令集。
