#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dfthub_g16_builder.py
--------------------------------------------------
读取 `Parameters` → 在 **g16 源码目录** 直接补丁 `utilnz.F` / `utilam.F` →
编译 Gaussian 16 → 输出目录统一命名为 **g16-opt**（若已存在则先删除）。

目录假定：
  当前目录/
        ├─ Parameters
        ├─ g16/
        └─ dfthub_g16_builder.py

运行：
    python3 dfthub_g16_builder.py                 # 补丁并编译
    python3 dfthub_g16_builder.py --dry-run       # 只检查，不修改文件、不编译
    python3 dfthub_g16_builder.py --parameters other/Parameters

改进：
  - 自动探测源码根目录（兼容 g16/ 与 g16/g16 两种布局）
  - 构建环境变量随实际路径调整
  - 按目标 block 搜索 utilnz.F / utilam.F 参数位置
  - 按参数名（而非文件顺序）读取 Parameters，规则与 CF22D_optimized_example.py 一致
  - --dry-run 可在修改源码前检查参数文件与源码 block
  - 类型标注兼容 Python 3.9+
"""

import argparse, sys, tarfile, shutil, subprocess, time
from pathlib import Path
from typing import Dict, List, Optional

# ───────────── 配置区 ─────────────
BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR

PARA_TXT  = ROOT_DIR / "Parameters"
G16_TARBZ = [ROOT_DIR / "g16.tar.gz", ROOT_DIR / "CF22Dg16.tar.gz"]
# ────────────────────────────────

CX_DIMS = [
    (0, 0, 6), (0, 1, 5), (0, 2, 4), (0, 3, 3),
    (1, 0, 5), (1, 1, 4), (1, 2, 3),
    (2, 0, 4), (2, 1, 3),
    (3, 0, 3),
]
CX_KEYS = [f"CX({i},{j},{k})" for i, j, n in CX_DIMS for k in range(n)]
CY_KEYS = [f"CY({i})" for i in range(9)]
CZ_KEYS = [f"CZ({i})" for i in range(9)]
PARAM_KEYS = CX_KEYS + CY_KEYS + CZ_KEYS


def log_step(name):
    def deco(func):
        def wrapper(*a, **kw):
            print(f"\n◯ {name} ...", flush=True)
            t0 = time.time(); out = func(*a, **kw)
            print(f"✅ {name} 完成（{time.time()-t0:.1f}s）", flush=True)
            return out
        return wrapper
    return deco


# ---------- 读取 Parameters ----------

def _parse_float(raw: str) -> float:
    return float(raw.replace('D', 'E').replace('d', 'e'))

def _format_hf(value: float, percent: bool) -> str:
    scale = 10000 if percent else 1000000
    return f"{int(round(value * scale)):06d}"

def read_para_vals(p: Path) -> List[str]:
    """按参数名读取 Parameters，返回 40 Cx + 9 Cy + 9 Cz（Fortran 格式）+ IMHF。

    解析规则与 CF22D_optimized_example.read_cf22d_parameters 相同：
    忽略 `#` 注释与未知键，键名不区分大小写/空白，支持 E 或 Fortran D 指数，
    参数顺序任意，重复出现的键取最后一个值。
    """
    if not p.exists():
        sys.exit(f"❌ Parameters 不存在 -> {p}")

    values: Dict[str, float] = {}
    hf: Optional[str] = None

    for lineno, ln in enumerate(p.read_text().splitlines(), 1):
        ln = ln.split('#', 1)[0].strip()
        if '=' not in ln:
            continue
        key, raw = [part.strip() for part in ln.split('=', 1)]
        key = _compact(key)
        if key not in ('HF', 'HF%') and key not in PARAM_KEYS:
            continue
        try:
            num = _parse_float(raw)
        except ValueError:
            sys.exit(f"❌ {p} 第 {lineno} 行无法解析数值：{ln}")
        if key == 'HF%':
            hf = _format_hf(num, percent=True)
        elif key == 'HF':
            hf = _format_hf(num, percent=False)
        else:
            values[key] = num

    missing = [k for k in PARAM_KEYS if k not in values]
    if hf is None:
        missing.append('HF% 或 HF')
    if missing:
        shown = ', '.join(missing[:5]) + (', ...' if len(missing) > 5 else '')
        sys.exit(f"❌ Parameters 中参数/HF 不足（缺少 {len(missing)} 项：{shown}）")

    vals = [
        f"{values[k]:.14e}".replace('e', 'D' if i < len(CX_KEYS) else 'd')
        for i, k in enumerate(PARAM_KEYS)
    ]
    return vals + [hf]


# ---------- 写 utilnz.F / utilam.F ----------

def _compact(s: str) -> str:
    return ''.join(s.split()).upper()

def _assignment_key(line: str) -> Optional[str]:
    if line[:1] in ('C', 'c', '*', '!'):
        return None
    left, sep, _ = line.partition('=')
    if not sep or left.lstrip().startswith('!'):
        return None
    return _compact(left)

def _find_section(
    lines: List[str],
    marker: str,
    src: Path,
    start: int = 0,
    end: Optional[int] = None,
) -> tuple:
    marker = _compact(marker)
    end = len(lines) if end is None else end
    matches = []
    for i in range(start, end):
        line = lines[i]
        if line[:1] in ('C', 'c', '*', '!'):
            continue
        if marker in _compact(line):
            section_start = i + 1
            section_end = end
            for j in range(section_start, end):
                key = _compact(lines[j].lstrip())
                if key.startswith('ELSEIF(') or key == 'ELSE':
                    section_end = j
                    break
            matches.append((section_start, section_end))
    if len(matches) != 1:
        locs = ', '.join(str(start + 1) for start, _ in matches) or '无'
        sys.exit(f"❌ {src} 中 {marker} block 数量应为 1，实际为 {len(matches)}（位置：{locs}）")
    return matches[0]

def _find_deck(lines: List[str], name: str, src: Path) -> tuple:
    marker = _compact(f"*Deck {name}")
    matches = []
    for i, line in enumerate(lines):
        if _compact(line) == marker:
            start = i + 1
            end = len(lines)
            for j in range(start, len(lines)):
                if _compact(lines[j]).startswith("*DECK"):
                    end = j
                    break
            matches.append((start, end))
    if len(matches) != 1:
        locs = ', '.join(str(start + 1) for start, _ in matches) or '无'
        sys.exit(f"❌ {src} 中 {marker} deck 数量应为 1，实际为 {len(matches)}（位置：{locs}）")
    return matches[0]

def _find_assignment_block(
    lines: List[str],
    keys: List[str],
    src: Path,
    label: str,
    start: int = 0,
    end: Optional[int] = None,
) -> int:
    keys = [_compact(k) for k in keys]
    end = len(lines) if end is None else end
    matches = []
    for i in range(start, end - len(keys) + 1):
        if all(_assignment_key(lines[i + j]) == keys[j] for j in range(len(keys))):
            matches.append(i)
    if len(matches) != 1:
        locs = ', '.join(str(i + 1) for i in matches) or '无'
        sys.exit(f"❌ {src} 中 {label} 参数 block 数量应为 1，实际为 {len(matches)}（位置：{locs}）")
    return matches[0]

def _replace_assignment(lines: List[str], idx: int, value: str, key: str, src: Path):
    line = lines[idx]
    left, sep, _ = line.partition('=')
    if not sep or _assignment_key(line) != _compact(key):
        sys.exit(f"❌ {src} 第 {idx+1} 行不是预期的 {key} 参数行：{line.rstrip()}")
    new = left + f"= {value}\n"
    changed = new != line
    lines[idx] = new
    return int(changed)

def _write_utils(g16_src: Path, v: List[str], dry_run: bool = False):
    nz, am = g16_src / "utilnz.F", g16_src / "utilam.F"
    if not nz.exists() or not am.exists():
        sys.exit(f"❌ 找不到 utilnz.F 或 utilam.F -> {nz} / {am}")

    nz_lines = nz.read_text().splitlines(True)
    am_lines = am.read_text().splitlines(True)

    nx_deck_start, nx_deck_end = _find_deck(nz_lines, "N12xP", nz)
    nx_start, nx_end = _find_section(nz_lines, "IFunc.eq.6", nz, nx_deck_start, nx_deck_end)
    cx_start = _find_assignment_block(nz_lines, CX_KEYS, nz, "Cx", nx_start, nx_end)

    cy_sec_start, cy_sec_end = _find_section(am_lines, "IFunc.eq.36", am)
    cy_start = _find_assignment_block(am_lines, CY_KEYS, am, "Cy", cy_sec_start, cy_sec_end)

    cz_sec_start, cz_sec_end = _find_section(am_lines, "IFunc.eq.37", am)
    cz_start = _find_assignment_block(am_lines, CY_KEYS, am, "Cz", cz_sec_start, cz_sec_end)

    hf_sec_start, hf_sec_end = _find_section(am_lines, "IMOpt.eq.-25", am)
    hf_idx = _find_assignment_block(am_lines, ["IMHF"], am, "IMHF", hf_sec_start, hf_sec_end)

    changed = 0
    for i, key in enumerate(CX_KEYS):
        changed += _replace_assignment(nz_lines, cx_start+i, v[i], key, nz)
    for i in range(9):
        changed += _replace_assignment(am_lines, cy_start+i, v[40+i], CY_KEYS[i], am)
    for i in range(9):
        changed += _replace_assignment(am_lines, cz_start+i, v[49+i], CY_KEYS[i], am)
    changed += _replace_assignment(am_lines, hf_idx, v[58], "IMHF", am)

    print(f"  Cx  : {nz} 第 {cx_start+1}-{cx_start+len(CX_KEYS)} 行")
    print(f"  Cy  : {am} 第 {cy_start+1}-{cy_start+9} 行")
    print(f"  Cz  : {am} 第 {cz_start+1}-{cz_start+9} 行")
    print(f"  IMHF: {am} 第 {hf_idx+1} 行 = {v[58]}")
    if dry_run:
        print(f"  dry-run：{changed} 行将被修改，未写入文件")
        return

    nz.write_text(''.join(nz_lines))
    am.write_text(''.join(am_lines))
    print(f"  已写入：{changed} 行被修改")


# ---------- 源码目录探测与编译 ----------

@log_step("准备 g16 源码")
def prepare_g16() -> Path:
    g16_dir = ROOT_DIR / "g16"
    if g16_dir.exists():
        return g16_dir
    tarball = next((p for p in G16_TARBZ if p.exists()), None)
    if tarball is None:
        names = " / ".join(str(p) for p in G16_TARBZ)
        sys.exit(f"❌ 未找到 g16 目录或源码压缩包 -> {g16_dir} / {names}")
    with tarfile.open(tarball, "r:*") as tar:
        tar.extractall(ROOT_DIR)
    return g16_dir


def detect_g16_src(base: Path) -> Path:
    candidates = [base / "g16", base]
    for cand in candidates:
        if (cand / "bsd" / "g16.profile").exists():
            return cand
    # 兼容非常规布局：在 base 下递归寻找一次
    try:
        prof = next((p for p in base.rglob("bsd/g16.profile")), None)
    except Exception:
        prof = None
    if prof:
        return prof.parent.parent
    sys.exit(f"❌ 未找到源码根目录（缺少 bsd/g16.profile）-> {base}")


@log_step("编译 Gaussian16")
def build_g16(src: Path):
    # 令 g16root/g16 指向实际源码目录 src
    env_root = src.parent
    cmd = (
        f'export g16root="{env_root}" && '
        'export GAUSS_EXEDIR="$g16root/g16" && '
        'source "$g16root/g16/bsd/g16.profile" && ./bsd/bldg16'
    )
    subprocess.run(cmd, shell=True, executable='/bin/bash', cwd=src, check=True)


@log_step("重命名为 g16-opt")
def rename_g16(top_level: Path):
    dst = ROOT_DIR / "g16-opt"
    shutil.rmtree(dst, ignore_errors=True)
    top_level.rename(dst)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="用 Parameters 中的 CF22D 参数补丁 Gaussian 16 源码并编译，输出 g16-opt/。",
    )
    parser.add_argument(
        "--parameters", type=Path, default=PARA_TXT, metavar="PATH",
        help="参数文件路径（默认：脚本同目录下的 Parameters）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只检查参数文件并定位源码中的参数 block，不修改源码、不编译（如无 g16/ 仍会解压源码包）",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None):
    args = parse_args(argv)
    vals = read_para_vals(args.parameters)
    g16_top = prepare_g16()
    g16_src = detect_g16_src(g16_top)
    _write_utils(g16_src, vals, dry_run=args.dry_run)
    if args.dry_run:
        print("\n✅ dry-run 完成：参数文件与源码 block 检查通过，未修改任何文件")
        return
    build_g16(g16_src)
    rename_g16(g16_top)


if __name__ == "__main__":
    main()
