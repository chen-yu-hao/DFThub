# DFThub Upload Template / DFThub 上传模板说明

This archive is a format reference for preparing custom training and optional test datasets in DFThub. Replace the example filenames, molecular geometries, and reference energies with your own data.

本压缩包为 DFThub 自定义训练集与可选测试集的标准格式模板。请将示例文件名、分子结构与参考能量替换为您自己的数据。

---

## 1. Training Upload Files / 训练集上传文件

Upload these files through **New job** (`upload/` directory):

在 **New job** 中上传以下文件（位于 `upload/` 目录）：

- `YourDatabaseName.tgz` (or `.zip` / `.tar.gz`): an archive containing `.xyz` geometry files (one molecule or transition state per file).
  包含 `.xyz` 分子结构文件的压缩包（每个文件对应一个分子或过渡态）。
- `YourDatabaseName.ref`: whitespace-separated reaction expressions and reference energies.
  以空白字符分隔的反应表达式与参考能量文件。

The molecule identifiers referenced in `.ref` must match the `.xyz` filenames without the `.xyz` extension (e.g., `Example_001` corresponds to `Example_001.xyz`).

`.ref` 文件中的分子名称必须与压缩包内的 `.xyz` 文件名（去掉 `.xyz` 后缀）严格一致（例如 `Example_001` 对应 `Example_001.xyz`）。

---

## 2. Geometry File Format (`.xyz`) / 分子结构文件格式 (`.xyz`)

Each `.xyz` file inside `YourDatabaseName.tgz` follows the standard Cartesian format with charge, spin multiplicity, and optional basis preset on line 2:

`YourDatabaseName.tgz` 中的每个 `.xyz` 文件采用标准笛卡尔坐标格式，其中**第 2 行**指定体系电荷、自旋多重度与可选基组：

```text
<natom>
<charge> <multiplicity> [basis]
<element> <x> <y> <z>
...
```

- **Line 1 (`<natom>`)**: Total number of atoms in the structure. / 原子总数。
- **Line 2 (`<charge> <multiplicity> [basis]`)**:
  - `<charge>`: Integer net molecular charge (e.g., `0`, `1`, `-1`). / 分子净电荷（整数，如 `0`、`1`、`-1`）。
  - `<multiplicity>`: Integer spin multiplicity $2S + 1$ (e.g., `1` for closed-shell singlet, `2` for doublet radical, `3` for triplet). / 自旋多重度 $2S + 1$（整数，如闭壳层单重态为 `1`，双重态自由基为 `2`）。
  - `[basis]` *(optional)*: Basis set preset when required by standalone scripts; web jobs use the basis selected at submission time. / 可选基组名称；Web 端提交任务时默认使用表单所选基组。
- **Line 3+ (`<element> <x> <y> <z>`)**: Atomic symbol and Cartesian coordinates in Å. / 元素符号与笛卡尔坐标（单位：Å）。

### Included Template Geometries (`H2` Bond Stretching) / 模板内置示例结构（$\text{H}_2$ 键长拉伸）

- `Example_001.xyz`: Stretched $\text{H}_2$ ($d_{\text{H-H}} = 1.00\text{ \AA}$, charge `0`, multiplicity `1`)
  拉伸态 $\text{H}_2$ 分子（键长 $1.00\text{ \AA}$，电荷 `0`，多重度 `1`）：
  ```text
  2
  0 1
  H 0.000000 0.000000 -0.500000
  H 0.000000 0.000000 0.500000
  ```
- `Example_002.xyz`: Equilibrium $\text{H}_2$ ($d_{\text{H-H}} = 0.74\text{ \AA}$, charge `0`, multiplicity `1`)
  平衡态 $\text{H}_2$ 分子（键长 $0.74\text{ \AA}$，电荷 `0`，多重度 `1`）：
  ```text
  2
  0 1
  H 0.000000 0.000000 -0.370000
  H 0.000000 0.000000 0.370000
  ```

---

## 3. Reference File Format (`.ref`) / 参考能量文件格式 (`.ref`)

Each line in `YourDatabaseName.ref` defines one stoichiometrically conserved reaction or energy difference using whitespace-separated columns:

`YourDatabaseName.ref` 的每一行定义一个化学计量守恒的反应或相对能量，各列以空格或制表符分隔：

### Even-Column Format (Recommended) / 偶数列格式（推荐）

```text
<coeff_1> <mol_1> [<coeff_2> <mol_2> ...] <ref_energy> <unit_scale>
```

- **Pairs of `<coeff_i> <mol_i>`**: Stoichiometric coefficient (positive for products/target state, negative for reactants/reference state) and molecule name (matching `<mol_i>.xyz`). Any number of molecules ($N \ge 1$, i.e. $\ge 4$ even columns total) is supported.
  `<coeff_i> <mol_i>` 配对：化学计量系数（产物/末态为正，反应物/初态为负）与分子名称（对应 `<mol_i>.xyz`）。支持任意数量的反应物/产物组合（$N \ge 1$，即总列数 $\ge 4$ 的任意偶数列）。
- **Second-to-last column (`<ref_energy>`)**: Reference reaction energy $\Delta E_{\text{ref}} = \sum_i \text{coeff}_i \cdot E(\text{mol}_i)$.
  倒数第二列（`<ref_energy>`）：反应参考能量 $\Delta E_{\text{ref}} = \sum_i \text{coeff}_i \cdot E(\text{mol}_i)$。
- **Last column (`<unit_scale>`)**: Unit / scaling divisor (`ratioo`). Set this column to **`1`** when `<ref_energy>` is already in **`kcal/mol`** (the residual is evaluated as $(\Delta E_{\text{calc, kcal/mol}} - \Delta E_{\text{ref}}) / \text{unit\_scale}$).
  最后一列（`<unit_scale>`）：单位缩放系数（`ratioo`）。当 `<ref_energy>` 单位为 **`kcal/mol`** 时，末尾列填写 **`1`**。

**Examples / 示例：**

1. **Relative energy of stretched vs. equilibrium $\text{H}_2$ (included in `YourDatabaseName.ref`) / 不同键长 $\text{H}_2$ 的相对能量（模板默认示例）：**
   $$E(\text{Example\_001}, d=1.00\text{ \AA}) - E(\text{Example\_002}, d=0.74\text{ \AA}) = 18.60\text{ kcal/mol}$$
   ```text
   1 Example_001 -1 Example_002 18.60000000 1
   ```
2. **$\text{H}_2 \rightarrow 2\text{H}$ bond dissociation energy / $\text{H}_2$ 解离能示例：**
   $$2 E(\text{H}) - 1 E(\text{H}_2) = 109.48\text{ kcal/mol}$$
   ```text
   2 H_atom -1 H2_mol 109.48000000 1
   ```

### Odd-Column Format (Hartree Legacy) / 奇数列格式（Hartree 单位兼容格式）

```text
<coeff_1> <mol_1> [<coeff_2> <mol_2> ...] <ref_energy_in_Hartree>
```

When the trailing `<unit_scale>` column is omitted (total columns $\ge 3$ and odd), `<ref_energy_in_Hartree>` is interpreted in **Hartree ($\text{E}_\text{h}$)** and automatically multiplied by `627.509` to convert to `kcal/mol`.

若省略末尾的单位系数列（总列数 $\ge 3$ 且为奇数），最后一列参考能量的单位默认为 **Hartree ($\text{E}_\text{h}$)**，解析器会自动乘以转换系数 `627.509` 转换为 `kcal/mol`。

---

## 4. Role of `init_weight.csv` / `init_weight.csv` 的作用

During job submission, `init_weight.csv` in the `upload/` directory specifies the uploaded dataset name and its initial **Inverse Weight** in the multi-objective loss function:

在提交新任务时，`upload/` 目录下的 `init_weight.csv` 用于记录用户上传数据集的名称及其在优化目标函数中的初始**逆权重（Inverse Weight）**：

```csv
Database,Description,Type,Source,Number,Inverse Weight
YourDatabaseName,H2 bond stretching relative energy,Input,uploaded,1,0.02
```

- The dataset name in the first column (`YourDatabaseName`) must match the archive prefix (`YourDatabaseName.tgz`).
  第一列数据集名称（`YourDatabaseName`）需与结构压缩包前缀（`YourDatabaseName.tgz`）一致。
- **Inverse Weight** (default `0.02`): Controls how strongly your dataset pulls on the functional fit (`weight = 1 / Inverse Weight`). **A smaller inverse weight gives your dataset higher priority** relative to the built-in benchmark databases (`default_weights.csv`). When the job starts, `init_weight.csv` is combined with `default_weights.csv` to form the run's `weight.csv`.
  **Inverse Weight（逆权重，默认 `0.02`）**：控制自定义数据集在泛函参数优化中的权重（实际权重为 `1 / Inverse Weight`）。**逆权重越小，您的训练集在拟合中所占比重越大**。任务启动时，后端会将 `init_weight.csv` 与内置基准库权重 `default_weights.csv` 合并生成当前运行的 `weight.csv`。

---

## 5. Optional Test Upload / 可选测试集上传

Upload a matching optional pair when independent evaluation is needed:

如需在不参与参数拟合的独立测试集上评估泛函表现，可同时上传以 `test_` 开头的配对文件：

- `test_YourTestSet.tgz`
- `test_YourTestSet.ref`

The test set is evaluated after fitting and during Input SCF; it is strictly excluded from parameter optimization.

测试集仅在参数拟合完成后及自洽场（Input SCF）阶段进行误差评估，绝不参与参数优化。
