import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
from pathlib import Path
from dfthub.pipeline.compute_scheduler import OPTIMIZER_THREADS, enter_task, limit_optimizer, thread_environment

os.environ.update(thread_environment(OPTIMIZER_THREADS))
from dfthub.pipeline.cf22d_baseline import native_cf22d_parameters
from dfthub.pipeline.refinement import optimizer_files, write_json
from dfthub.pipeline.testset_inheritance import ensure_fork_test_set
from dfthub.pipeline.optimization_runtime import OPTIMIZATION_FTOL

from dfthub.paths import optimizer_dir, data_dir
TMB11_DIR = optimizer_dir()
DEMO_ROOT = Path(os.environ.get("DFTHUB_DEMO_ROOT", str(data_dir() / "optimizer")))
DEMO_ROOT.mkdir(parents=True, exist_ok=True)

_CX_GROUPS = [
    (0, 0, 6), (0, 1, 5), (0, 2, 4), (0, 3, 3),
    (1, 0, 5), (1, 1, 4), (1, 2, 3),
    (2, 0, 4), (2, 1, 3),
    (3, 0, 3),
]
_HF_PERCENT = "5.2172460196608100e+01"


def generate_parameters(params_path, output_path):
    with open(params_path) as f:
        values = [line.strip() for line in f if line.strip()]
    if len(values) != 59:
        print(f"[warn] expected 59 params, got {len(values)}; skipping Parameters generation")
        return

    lines = ["Parameters"]
    idx = 0
    for n, j, count in _CX_GROUPS:
        for k in range(count):
            lines.append(f"Cx({n},{j},{k}) = {float(values[idx]):.16e}")
            idx += 1

    # HF exact-exchange mixing is now the optimized 59th parameter.
    lines.append(f"HF% = {float(values[58]) * 100:.16e}")

    for i in range(9):
        lines.append(f"Cy({i}) = {float(values[40 + i]):.16e}")

    for i in range(9):
        lines.append(f"Cz({i}) = {float(values[49 + i]):.16e}")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"generated Parameters -> {output_path}")


def generate_mue(results_path, output_path, weights=None):
    with open(results_path) as f:
        results = json.load(f)

    lines = ["------------SUMMARY-------------"]
    mues = []
    weighted_rmse_sum = 0.0
    for key, val in results.items():
        if key in ("a", "b", "c"):
            continue
        if not isinstance(val, dict) or "MUE" not in val:
            continue
        name = key.replace("_ref", "")
        if name == "INPUT":
            name = "input"
        mue_val = val["MUE"]
        lines.append(f"{name}\t{mue_val}")
        mues.append(mue_val)
        rmse_val = val.get("RMSE", 0.0)
        w = weights.get(key, 1.0) if weights else 1.0
        weighted_rmse_sum += rmse_val / w

    total_mue = sum(mues) / len(mues) if mues else 0.0
    lines.append(f"new_total_mue:{total_mue}")

    reg_a = results.get("a", {}).get("RMSE", 0.0)
    reg_b = results.get("b", {}).get("RMSE", 0.0)
    reg_c = results.get("c", {}).get("RMSE", 0.0)
    reg_loss = 0.01 * (reg_a + reg_b + reg_c)
    total_loss = weighted_rmse_sum + reg_loss

    lines.append("")
    lines.append("------------LOSS----------------")
    lines.append(f"Weighted MUE sum:\t{weighted_rmse_sum:.4f}")
    lines.append(f"Regularization (0.01*(a+b+c)):\t{reg_loss:.4f}")
    lines.append(f"Total loss:\t{total_loss:.4f}")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"generated Mue -> {output_path}")


def read_weights_csv(csv_path):
    """Read weight.csv and return {ref_name: inverse_weight} dict."""
    weights = {}
    with open(csv_path) as f:
        for line in f.readlines()[1:]:
            fields = re.split(r"[\t,]", line.strip())
            if len(fields) < 2:
                continue
            db_name = fields[0].strip()
            if not db_name:
                continue
            try:
                inv_w = float(fields[-1])
            except ValueError:
                continue
            is_uploaded = len(fields) >= 4 and "uploaded" in fields[3]
            ref_key = "INPUT_ref" if is_uploaded else f"{db_name}_ref"
            weights[ref_key] = inv_w
    return weights


def evaluate_optional_test_set(output_dir):
    """Evaluate TEST_INPUT after fitting; never add it to TrainDataSet."""
    output_dir = Path(output_dir)
    descriptors = output_dir / "TEST_INPUT"
    reference = output_dir / "TEST_INPUT_ref"
    params = output_dir / "NEW-params.txt"
    metadata = output_dir / "OriginalMue.meta.json"
    if not all(path.is_file() for path in (descriptors, reference, params, metadata)):
        return
    evaluator = Path(__file__).with_name("evaluate_test_set.py")
    result = subprocess.run([
        sys.executable, str(evaluator), "--descriptors", str(descriptors),
        "--reference", str(reference), "--params", str(params),
        "--original-meta", str(metadata), "--output", str(output_dir / "TestMue.json"),
    ], capture_output=True, text=True)
    (output_dir / "test-evaluate.log").write_text(result.stdout + "\n" + result.stderr)
    if result.returncode != 0:
        raise RuntimeError("Optional test set evaluation failed; see test-evaluate.log")
    print("Optional test set evaluated; optimization objective was unchanged")
def build_demo(demo_name, fit_file, ref_file, inverse_weight, maxiter, all_weights=None,
               template_dir=None, initial_params=None):
    demo_dir = Path(tempfile.mkdtemp(prefix=f"demo_{demo_name}_", dir=DEMO_ROOT))
    source = Path(template_dir) if template_dir else TMB11_DIR
    optimizer_files(source, demo_dir)
    if initial_params:
        import numpy as np
        values = np.loadtxt(initial_params)
        if values.shape != (59,) or not np.all(np.isfinite(values)):
            raise ValueError("Expected 59 finite parent parameters")
        shutil.copy2(initial_params, demo_dir / "params.txt")

    shutil.copy(fit_file, demo_dir / "Database_updated/fit/INPUT")
    shutil.copy(ref_file, demo_dir / "Database_updated/ref/INPUT_ref")

    opt_src = (source / "opt.py").read_text()
    # Frozen templates must inherit the shared scheduler's thread settings.
    opt_src = re.sub(
        r'^os\.environ\[(?:"|\x27)(?:XLA_FLAGS|OMP_NUM_THREADS|MKL_NUM_THREADS|OPENBLAS_NUM_THREADS)(?:"|\x27)\]\s*=.*\n',
        '', opt_src, flags=re.MULTILINE,
    )

    if all_weights:
        # Replace the entire weight={...} block in opt.py
        weight_entries = ",\n ".join(
            f"'{k}': {v}" for k, v in all_weights.items()
        )
        new_weight_block = f"weight ={{{weight_entries}}}"
        opt_src = re.sub(
            r"weight\s*=\s*\{[^}]+\}",
            new_weight_block,
            opt_src,
            count=1,
            flags=re.DOTALL,
        )
    else:
        opt_src, n = re.subn(
            r"'INPUT_ref':\s*[-+\d.eE]+",
            f"'INPUT_ref': {inverse_weight}",
            opt_src,
        )
        if n != 1:
            raise RuntimeError(f"expected exactly one 'INPUT_ref' weight entry in opt.py, patched {n}")

    if maxiter != 10000:
        opt_src = opt_src.replace("maxiter=10000", f"maxiter={maxiter}")
    # Normalize inherited snapshots to the template entry point before injecting
    # the current shared convergence runner.
    opt_src = opt_src.replace("from optimization_runtime import run_optimization\n", "")
    opt_src = opt_src.replace("res = run_optimization(solver, theta0)", "res = solver.run(theta0)")
    baseline_marker = "res = solver.run(theta0)"
    if opt_src.count(baseline_marker) != 1:
        raise RuntimeError("Expected one optimizer entry point for original MUE capture")
    native = native_cf22d_parameters()
    (demo_dir / "OriginalMue.meta.json").write_text(json.dumps(native, indent=2) + "\n")
    if "_native_cf22d = _baseline_json.load" not in opt_src:
        opt_src = opt_src.replace(baseline_marker,
        "from saver import save_dict_to_json\n"
        "import json as _baseline_json\n"
        "import numpy as np\n"
        "with open('OriginalMue.meta.json') as _baseline_file:\n"
        "    _native_cf22d = _baseline_json.load(_baseline_file)\n"
        "_baseline_theta = np.asarray(_native_cf22d['coefficients'], dtype=np.float64)\n"
        "save_dict_to_json(residual_dataset_all(_baseline_theta), 'original_results.json')\n"
        + baseline_marker)
    opt_src = opt_src.replace(baseline_marker,
        "from optimization_runtime import run_optimization\n"
        "res = run_optimization(solver, theta0)")
    shutil.copy2(Path(__file__).with_name("optimization_runtime.py"), demo_dir / "optimization_runtime.py")
    (demo_dir / "opt.py").write_text(opt_src)
    return demo_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fit", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--inverse-weight", type=float, default=0.02)
    parser.add_argument("--output", required=True)
    parser.add_argument("--demo-name", default="job")
    parser.add_argument("--maxiter", type=int, default=10000)
    parser.add_argument("--weights-csv", default=None,
                        help="weight.csv with all database inverse weights (overrides --inverse-weight)")
    parser.add_argument("--template-dir", help="Frozen parent optimizer workspace")
    parser.add_argument("--initial-params", help="Parent optimized parameters used as the starting point")
    args = parser.parse_args()
    enter_task(args.output, OPTIMIZER_THREADS)
    inherited = ensure_fork_test_set(args.output)
    if inherited:
        print(f"Inherited {len(inherited)} optional test input files; test data remain excluded from optimization", flush=True)

    all_weights = None
    if args.weights_csv:
        all_weights = read_weights_csv(args.weights_csv)
        print(f"Resubmit: loaded {len(all_weights)} database weights from weight.csv")
    print(f"Resubmit: reusing DFT descriptors (INPUT/INPUT_ref), skipping DFT computation")

    demo_dir = build_demo(args.demo_name, args.fit, args.ref, args.inverse_weight, args.maxiter, all_weights,
                          args.template_dir, args.initial_params)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    frozen = output_dir / "optimizer_snapshot"
    if not frozen.exists():
        temporary = output_dir / ".optimizer_snapshot"
        temporary.mkdir(exist_ok=True)
        optimizer_files(demo_dir, temporary)
        temporary.rename(frozen)
    print(f"Optimizer workspace ready")

    print("Optimizing parameters.....")
    t_opt_start = time.time()
    # CPU quota limits the optimizer and BLAS without fixing CPU IDs.
    limit_optimizer()
    opt_env = thread_environment(OPTIMIZER_THREADS)
    opt_env.update({
        "DFTHUB_OPT_STATUS_PATH": str(output_dir.resolve() / "OptimizationStatus.json"),
    })
    opt_cmd = [sys.executable, "opt.py"]
    print(f"Optimizer CPU budget: {OPTIMIZER_THREADS}; no CPU affinity binding", flush=True)
    status_file = output_dir / "OptimizationStatus.json"
    write_json(status_file, {"status": "Running", "converged": False, "method": "SLSQP",
                             "ftol": OPTIMIZATION_FTOL, "started_at": time.time()})
    result = subprocess.run(opt_cmd, cwd=demo_dir, env=opt_env)
    t_opt_end = time.time()
    status = json.loads(status_file.read_text())
    if result.returncode != 0 or not status.get("converged"):
        if status.get("status") != "Failed":
            status.update(status="Failed", converged=False, process_returncode=result.returncode,
                          error="Optimizer process ended without confirmed convergence", finished_at=time.time())
            write_json(status_file, status)
        print(f"[Error] {status.get('error', 'Parameter optimization did not converge')}")
        sys.exit(result.returncode or 1)
    print(f"Parameters optimization finished, outputting results......")
    print(f"The runtime for the optimization function is: {(t_opt_end - t_opt_start) / 60:.2f} min")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("NEW-params.txt", "results.json", "original_results.json", "OriginalMue.meta.json"):
        src_f = demo_dir / fname
        if src_f.exists():
            shutil.copy(src_f, output_dir / fname)
            print(f"  {fname} -> {output_dir}")

    params_file = output_dir / "NEW-params.txt"
    results_file = output_dir / "results.json"
    if params_file.exists():
        generate_parameters(params_file, output_dir / "Parameters")
    if results_file.exists():
        _wcsv = Path(args.weights_csv) if args.weights_csv else None
        weights = read_weights_csv(str(_wcsv)) if _wcsv and _wcsv.exists() else None
        generate_mue(results_file, output_dir / "Mue", weights=weights)
        original_results = output_dir / "original_results.json"
        if original_results.exists():
            generate_mue(original_results, output_dir / "OriginalMue", weights=weights)
        with open(results_file) as _rf:
            _res = json.load(_rf)
        _reg_a = _res.get("a", {}).get("RMSE", 0.0)
        _reg_b = _res.get("b", {}).get("RMSE", 0.0)
        _reg_c = _res.get("c", {}).get("RMSE", 0.0)
        _weighted_sum = 0.0
        for _k, _v in _res.items():
            if _k in ("a", "b", "c") or not isinstance(_v, dict) or "RMSE" not in _v:
                continue
            _w = weights.get(_k, 1.0) if weights else 1.0
            _weighted_sum += _v["RMSE"] / _w
        _reg_loss = 0.01 * (_reg_a + _reg_b + _reg_c)
        _total_loss = _weighted_sum + _reg_loss
        print(f"Final loss: {_total_loss:.4f} (weighted_sum={_weighted_sum:.4f}, reg={_reg_loss:.4f})")

    evaluate_optional_test_set(output_dir)

    print(f"Optimized parameters available in {output_dir}")
