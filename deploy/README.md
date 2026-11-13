# 离线部署

## Python 准备

推荐独立 CPython 3.12 venv；也支持 3.10/3.11 的当前补丁版。Conda 用户可以使用 `conda/environment.yml` 后执行 `conda/install-release.sh`。不要把旧服务器绝对路径或 site-packages 复制到新机器。

- Ubuntu 22.04+ x86_64：安装所选版本 Python、对应 venv 支持和系统 C 运行库。离线机器需提前通过发行版包管理器准备安装介质。
- macOS Apple Silicon：安装 arm64 Python 3.10–3.12，避免 Rosetta x86_64 解释器；v0.1.1 需按源码构建步骤编译最新 DFT 引擎。
- Conda：联网机先创建 `conda create -n dfthub python=3.12 pip`，或提前准备同架构离线 conda 包；DFThub wheelhouse 不携带 Python。

Linux Release 离线包命名包含架构和 `cp310/cp311/cp312`。解压后运行：

```bash
DFTHUB_INSTALL_PYTHON=python3.12 bash deploy/install-offline.sh /opt/dfthub/.venv
/opt/dfthub/.venv/bin/dfthub doctor --strict
/opt/dfthub/.venv/bin/dfthub serve --data-dir /var/lib/dfthub/data
```

安装器先验证平台和 SHA256SUMS，再用 `--no-index --require-hashes` 安装所有依赖。无匹配 wheel 时明确失败，不在断网机器上尝试编译或获取上游 PySCF。所有科学库、静态页面和 Swagger UI 资源都包含在发行包中。Conda 安装路径同样使用这个 wheelhouse，不从 Conda/PyPI 安装上游 `pyscf`；macOS 使用源码构建路径。

## 配置、路径和迁移

本地使用无需环境文件：`dfthub serve` 只监听 127.0.0.1:8188，数据放在 XDG data home 下的 dfthub，且不发送邮件；加 `--local` 还可以免去注册和登录（见下文“本地单用户模式”）。服务器部署时，复制 `dfthub.env.example` 到安装目录和仓库之外，`chmod 600`，并设置 `DFTHUB_ENV_FILE` 指向它。DFThub 只读取这一个环境文件，不会自动加载源码目录中的 `.env`。

文件格式为每行一个 `KEY=value`，`#` 开头的行是注释，值后面不能再写注释；空值（`KEY=`）视为未设置。现有进程环境优先，命令行 `--data-dir/--python` 优先于两者。开关类设置接受 `1`/`0`（也接受 true/false、yes/no、on/off），其他值会让服务报错退出而不是猜测。文件不存在、权限不是 0600/0400 或某行格式错误时，`dfthub serve` 会给出文件名和行号并退出。

| 配置 | 默认值/用途 |
|---|---|
| DFTHUB_DATA_DIR | XDG data home 下的 dfthub；账号、任务、模板、检查点 |
| DFTHUB_PYTHON | 当前解释器；独立计算环境也需安装 DFThub 和 DFT 引擎 |
| DFTHUB_TMB11_DIR | 包内只读 optimizer 资源 |
| DFTHUB_DEMO_ROOT | 数据目录下的 optimizer，可写临时优化目录 |
| DFTHUB_SCHEDULER_DIR | 数据目录下 scheduler |
| DFTHUB_AME418_ROOT | 外部 AME418 初始计算数据；最小包不含大型检查点 |
| DFTHUB_ENV_FILE | 环境文件路径；本地使用无需设置 |
| DFTHUB_PUBLIC_URL | 站点公开地址，用于邮件中的链接；默认 http://127.0.0.1:8188 |
| DFTHUB_ENABLE_HSTS | 0；HTTPS 生效后才设为 1 |
| JWT_SECRET | 登录令牌签名密钥；默认首次启动时在数据目录生成 `.jwt_secret` |
| DFTHUB_MAIL_SUPPRESS | 1（关闭）；开启邮件时显式设为 0 |
| DFTHUB_MAIL_SERVER / DFTHUB_MAIL_PORT | SMTP 服务器与端口；默认 localhost:25 |
| DFTHUB_MAIL_USE_TLS / DFTHUB_MAIL_USE_SSL | STARTTLS（常用 587）或 SSL（常用 465），二选一；默认均为 0 |
| DFTHUB_MAIL_USERNAME / DFTHUB_MAIL_PASSWORD | SMTP 登录凭据；不会打印、记录或经 API 返回 |
| DFTHUB_MAIL_SENDER | 发件人；默认 `DFThub <noreply@localhost>` |
| DFTHUB_CPU_THREADS / DFTHUB_MEMORY_MB | CPU/内存预约池，默认自动探测 |
| DFTHUB_TASK_THREADS / DFTHUB_OPTIMIZER_THREADS | 每项任务的最大线程数 |

现有服务器迁移：停服务，复制整个旧 `dft_files` 为新数据目录；把需要恢复的历史 `demo_*` 单独复制到 `DFTHUB_DEMO_ROOT`。旧 Work/common/program 副本不再作为程序入口，发行包使用其自身固定版本。已有输出、test_set 和 input_srp 目录原样保留。不要把工作目录打进公开发布包。

新 fork 和 SCF 快照的几何输入目录名为 `inputs/`，避免 macOS 默认磁盘将旧 `input/` 目录与 `INPUT` 描述符文件视为同名。Linux 上仍可读取旧布局。把旧 Linux 数据搬到 macOS 前，应在 Linux 的停机备份副本上先运行 `python tools/migrate_data_layout.py --data-dir /backup/dft_files` 查看清单，再加 `--apply` 重命名目录，之后传输整个副本。不要先把存在大小写冲突的数据复制到 macOS。

服务默认监听 127.0.0.1:8188。对外服务可用 nginx/Caddy 转发整个站点；API 和前端同源。HTTPS 由反向代理管理，仅在 HTTPS 下设 `DFTHUB_ENABLE_HSTS=1`。用进程管理器启动 `dfthub serve`，不要用多个 WSGI 进程共享一个内存队列。CLI 锁定数据目录以避免双实例。

## 本地单用户模式

只有自己使用的电脑上，可以用 `dfthub serve --local` 关闭注册和登录。页面直接进入账号 `local` 的工作区；该账号在首次启动时创建，没有邮箱，也没有可用的密码。

```bash
dfthub serve --local
dfthub serve --local --local-user alice   # 改用已有账号及其任务
```

- `--local` 只能配合回环地址的 `--host`（默认 `127.0.0.1`，或 `::1`）；其他地址会在服务启动前被拒绝。用 http://127.0.0.1:8188 或 http://localhost:8188 打开。
- 能使用这台电脑的任何人（包括其他系统用户和程序）都可以不输密码、以该账号使用 DFThub。不要在多人共用的机器上使用 `--local`。
- 不要在 `--local` 前面加反向代理。会话只发给直接来自本机的请求：带代理头（`Forwarded`、`X-Forwarded-For`、`X-Forwarded-Host`、`X-Real-IP`）、使用其他主机名或来自其他来源页面的请求都会被拒绝；但不添加这些头的代理仍会暴露该账号。
- `--local` 运行期间，注册和密码登录关闭。由 `--local` 创建的账号没有可用的密码，请继续用 `--local` 启动。
- 其他接口仍需令牌；页面通过只在本地模式下响应的 `POST /api_dft/local-session` 获取。

## 邮件与隐私

默认不发送任何邮件。网页不加载外部资源，也没有遥测；服务自身唯一的对外连接是开启邮件后连接你配置的 SMTP 服务器。`dfthub serve` 启动时会打印邮件状态，例如 `Mail: off (no e-mail is sent)` 或 `Mail: on via smtp.example.org:587 (STARTTLS, with SMTP login), sender ...`。

**账号与邮箱。** 注册时邮箱是可选的，可以用用户名或邮箱登录。邮件关闭时，新建任务表单不会要求填写邮箱，任务也不保存任何地址；邮件开启时，表单要求填写通知地址，账号有邮箱时自动填入。

**发送内容与时机。** 开启后，任务提交时以及完成或失败时，DFThub 会给任务所有者发邮件。邮件包含用户名、任务名、Run 名和指向 `DFTHUB_PUBLIC_URL` 的链接，不含计算结果或上传的文件。邮件经由你配置的 SMTP 服务器发送，该服务商能看到邮件内容。

**开启方法。** 在环境文件中取消注释整个邮件段，包括开关：

```text
DFTHUB_MAIL_SUPPRESS=0
DFTHUB_MAIL_SERVER=smtp.example.org
DFTHUB_MAIL_PORT=587
DFTHUB_MAIL_USE_TLS=1
DFTHUB_MAIL_USERNAME=your-account
DFTHUB_MAIL_PASSWORD=replace-me
DFTHUB_MAIL_SENDER=DFThub <noreply@example.org>
DFTHUB_PUBLIC_URL=https://dfthub.example.org
```

只填 SMTP 设置而不设 `DFTHUB_MAIL_SUPPRESS=0` 时邮件仍是关闭的，启动信息会提示这一点。`DFTHUB_MAIL_USE_TLS=1` 与 `DFTHUB_MAIL_USE_SSL=1` 只能二选一。

**SMTP 凭据。** 只从进程环境或 `DFTHUB_ENV_FILE` 指定的文件（权限必须是 0600 或 0400）读取，不会打印或写入日志，也没有任何 API 返回它们。请把该文件放在安装目录和 Git 仓库之外。

**DFThub 保存的用户信息。** 全部位于数据目录：

- `auth.db`（权限 0600）：用户名、邮箱地址（如果填写了）、加盐的密码哈希和创建时间。邮箱不做验证，只用于登录和通知。
- `.jwt_secret`（权限 0600）：登录令牌的签名密钥。令牌有效期 7 天，保存在浏览器 local storage 中，内含用户 ID、用户名和邮箱（如有）。
- 邮件开启时，任务的通知地址只在任务排队和运行期间保存在内存中，不写入任务文件。投递失败时会记录 `[mail] ... error: ...`，SMTP 服务器的错误信息可能包含收件地址。

**公网部署。** 提交任务时，已登录用户可以填写另一个通知地址。注册是开放的，因此在任何人都能访问且开启了邮件的服务器上，任何人都可以注册账号，让你的 SMTP 账号向任意地址发送通知邮件。请按主 README 的 Public access 一节限制访问，或保持邮件关闭。

## 从固定源代码构建引擎

在联网构建机准备 Python 的 `build wheel setuptools cmake<4`；Linux 还需 C/C++ 编译器、OpenBLAS 开发库、auditwheel、patchelf；macOS arm64 需 Xcode command-line tools、Homebrew llvm/libomp/openblas 和 delocate。

```bash
git clone --branch DFT https://github.com/chen-yu-hao/pyscf.git .build/pyscf
# 也可使用 git@github.com:chen-yu-hao/pyscf.git
git -C .build/pyscf checkout e7cb735789293acf461f8ebbb4ac6a08b68ba5d6
python tools/build_engine.py --source .build/pyscf --output dist/engine
python -m build
python tools/offline_bundle.py --engine dist/engine/dfthub_pyscf_dft-*.whl --package dist/dfthub-0.1.1-py3-none-any.whl
```

macOS 的 LLVM/OpenBLAS flags 与完整构建流程见 `.github/workflows/release.yml`；设置 `CMAKE_OSX_ARCHITECTURES=arm64`、`_PYTHON_HOST_PLATFORM=macosx-14.0-arm64` 及 `DFTHUB_MACOS_LIBOMP` 指向 Homebrew libomp.dylib。修复 wheel 时统一 OpenMP 动态库引用，避免不同 Homebrew 前缀的同名库冲突。引擎源码包也作为 Release 资产保存。源码回退构建需要获得 LibXC/libcint/XCFun 源码和工具链；离线安装使用预编译 wheelhouse，无需编译器。不要启用 `-march=native`，以免发行包绑定构建机指令集。
构建脚本会写入最新 DFT 提交 `e7cb735789293acf461f8ebbb4ac6a08b68ba5d6` 的源码归档和 provenance；不要使用旧版 `v0.1.0` wheel 代替本次构建。
