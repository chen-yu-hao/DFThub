# DFThub

DFThub 示例仓库，当前提供一个由 DFThub 生成的 PySCF 自定义泛函输入文件：`CF22D_optimized_example.py`。

该示例将 CF22D 泛函参数注册到 PySCF/libxc 中，并演示如何在 PySCF 的 `RKS` 计算中调用该泛函。

## 当前内容

- `CF22D_optimized_example.py`：CF22D 泛函参数与 PySCF 注册示例。
- `register_cf22d(mf, name="cf22d_custom")`：将 CF22D 注册为 PySCF 可用的自定义泛函，并把 `mf.xc` 设置为对应名称。
- 脚本末尾包含一个 H2 分子的最小运行示例。

## 环境要求

- Python 3
- NumPy
- PySCF >= 2.4
- 支持 CF22D 的 libxc/PySCF 构建

安装依赖：

```bash
pip install numpy pyscf
```

## 快速开始

克隆仓库：

```bash
git clone https://github.com/chen-yu-hao/DFThub.git
cd DFThub
```

运行示例：

```bash
python CF22D_optimized_example.py
```

脚本会执行一个 H2 分子的 `RKS` 计算，并输出总能量。

## 在自己的 PySCF 脚本中使用

```python
from pyscf import gto, dft
from CF22D_optimized_example import register_cf22d

mol = gto.M(atom="H 0 0 0; H 0 0 0.74", basis="def2-qzvp")
mf = dft.RKS(mol)
mf.grids.level = 6

register_cf22d(mf)
mf.kernel()

print(mf.e_tot)
```

如需自定义内部名称，可以传入 `name`：

```python
register_cf22d(mf, name="my_cf22d")
```

## 文件结构

```text
.
├── CF22D_optimized_example.py
└── README.md
```

## 参考文献

Y. Liu, C. Zhang, Z. Liu, D. G. Truhlar, Y. Wang, X. He, "Supervised Learning of a Chemistry Functional with Damped Dispersion", *Nature Computational Science*, 2023, 3, 48-58.

## 许可

本仓库目前尚未提供明确的开源许可证。使用、修改或分发前，请先确认授权范围。
