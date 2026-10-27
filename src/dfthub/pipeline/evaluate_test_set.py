"""Evaluate an optional test descriptor set without touching the optimizer objective."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

HARTREE_TO_KCAL = 627.509


def parse_ref_line(line: str):
    parts = line.split()
    if len(parts) < 3:
        return None
    if len(parts) % 2 == 0:
        coeffs = [float(parts[i]) for i in range(0, len(parts) - 2, 2)]
        names = [parts[i] for i in range(1, len(parts) - 1, 2)]
        ref = float(parts[-2]); ratio = float(parts[-1]); scale = 1.0
    else:
        coeffs = [float(parts[i]) for i in range(0, len(parts) - 1, 2)]
        names = [parts[i] for i in range(1, len(parts) - 1, 2)]
        ref = float(parts[-1]); ratio = 1.0; scale = HARTREE_TO_KCAL
    return coeffs, names, ref, ratio, scale


def load_rows(path: Path):
    rows = {}
    for line in path.read_text().splitlines():
        fields = line.split()
        if not fields:
            continue
        values = np.asarray([float(value) for value in fields[1:]], dtype=float)
        if values.shape != (62,) or not np.isfinite(values).all():
            raise ValueError(f"Invalid test descriptor row: {fields[0]}")
        rows[fields[0]] = values
    if not rows:
        raise ValueError("Test descriptor set is empty")
    return rows


def evaluate(rows, reference: Path, params, original):
    optimized = {}
    native = {}
    for name, row in rows.items():
        optimized[name] = float(row[0] + np.dot(row[1:60] - row[0], params) + row[60] + row[61] / HARTREE_TO_KCAL)
        native[name] = float(row[0] + np.dot(row[1:60] - row[0], original) + row[60] + row[61] / HARTREE_TO_KCAL)

    def collect(energies):
        errors = []
        rows_out = []
        for line in reference.read_text().splitlines():
            parsed = parse_ref_line(line)
            if parsed is None:
                continue
            coeffs, names, ref, ratio, scale = parsed
            if any(name not in energies for name in names):
                continue
            calc = sum(coeff * energies[name] for coeff, name in zip(coeffs, names)) * HARTREE_TO_KCAL / ratio
            target = ref * scale / ratio
            error = calc - target
            errors.append(abs(error))
            rows_out.append({"system": "+".join(f"{c:g}*{n}" for c, n in zip(coeffs, names)),
                             "reference": round(target, 6), "calculated": round(calc, 6),
                             "unbiasedError": round(abs(error), 6)})
        return rows_out, round(sum(errors) / len(errors), 6) if errors else None

    return collect(optimized), collect(native)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--descriptors", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--original-meta", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows = load_rows(Path(args.descriptors))
    params = np.asarray([float(value) for value in Path(args.params).read_text().split()], dtype=float)
    if params.shape != (59,) or not np.isfinite(params).all():
        raise ValueError("Optimized parameters must contain 59 finite values")
    meta = json.loads(Path(args.original_meta).read_text())
    original = np.asarray(meta["coefficients"], dtype=float)
    if original.shape != (59,) or not np.isfinite(original).all():
        raise ValueError("Native CF22D metadata is invalid")
    optimized, baseline = evaluate(rows, Path(args.reference), params, original)
    payload = {"scope": "test", "complete": bool(optimized[0]), "dataset": "test",
               "targetRows": optimized[0], "targetMue": optimized[1],
               "originalRows": baseline[0], "originalMue": baseline[1],
               "count": len(optimized[0])}
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n")
    Path(str(args.output).replace("TestMue.json", "TestMue")).write_text(
        "------------SUMMARY-------------\n" + (f"test_input\t{optimized[1]}\n" if optimized[1] is not None else "") +
        "------------LOSS----------------\n")
    Path(str(args.output).replace("TestMue.json", "TestOriginalMue")).write_text(
        "------------SUMMARY-------------\n" + (f"test_input\t{baseline[1]}\n" if baseline[1] is not None else "") +
        "------------LOSS----------------\n")
    Path(str(args.output).replace("TestMue.json", "TestOriginalMue.meta.json")).write_text(
        json.dumps({"source": meta.get("source"), "functional": meta.get("functional"),
                    "parameter_sha256": meta.get("parameter_sha256"), "scope": "test"}, indent=2) + "\n")


if __name__ == "__main__":
    main()
