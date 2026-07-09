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
    python3 dfthub_g16_builder.py

改进：
  - 自动探测源码根目录（兼容 g16/ 与 g16/g16 两种布局）
  - 构建环境变量随实际路径调整
  - 按目标 block 搜索 utilnz.F / utilam.F 参数位置
  - 类型标注兼容 Python 3.9+
"""

import sys, tarfile, shutil, subprocess, time
from pathlib import Path
from typing import List, Optional

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

def _format_hf(raw: str, key: str) -> str:
    value = float(raw)
    scale = 10000 if '%' in key else 1000000
    return f"{int(round(value * scale)):06d}"

def read_para_vals(p: Path) -> List[str]:
    if not p.exists():
        sys.exit(f"❌ Parameters 不存在 -> {p}")

    lines = [l.strip() for l in p.read_text().splitlines() if l.strip()]
    vals: List[str] = []
    hf: Optional[str] = None

    for ln in lines:
        if '=' not in ln:
            continue
        key, raw = [part.strip() for part in ln.split('=', 1)]
        if 'HF' in key.upper():
            try:
                hf = _format_hf(raw, key)
            except ValueError:
                pass
        elif len(vals) < 58:
            try:
                num = float(raw)
                fmt = 'D' if len(vals) < 40 else 'd'
                vals.append(f"{num:.14e}".replace('e', fmt))
            except ValueError:
                pass

    if len(vals) < 58 or hf is None:
        sys.exit("❌ Parameters 中参数/HF 不足")

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
    lines[idx] = left + f"= {value}\n"

def _write_utils(g16_src: Path, v: List[str]):
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

    for i, key in enumerate(CX_KEYS):
        _replace_assignment(nz_lines, cx_start+i, v[i], key, nz)
    for i in range(9):
        _replace_assignment(am_lines, cy_start+i, v[40+i], CY_KEYS[i], am)
    for i in range(9):
        _replace_assignment(am_lines, cz_start+i, v[49+i], CY_KEYS[i], am)
    _replace_assignment(am_lines, hf_idx, v[58], "IMHF", am)

    nz.write_text(''.join(nz_lines))
    am.write_text(''.join(am_lines))


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


def main():
    vals = read_para_vals(PARA_TXT)
    g16_top = prepare_g16()
    g16_src = detect_g16_src(g16_top)
    _write_utils(g16_src, vals)
    build_g16(g16_src)
    rename_g16(g16_top)


if __name__ == "__main__":
    main()
