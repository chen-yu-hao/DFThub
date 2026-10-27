"""Shared convergence policy for NumPy/SciPy optimization."""
import json
import math
import os
import time
from pathlib import Path

import numpy as np

OPTIMIZATION_FTOL = 1e-12


def save_status(report):
    targets = {Path("OptimizationStatus.json").resolve()}
    if os.environ.get("DFTHUB_OPT_STATUS_PATH"):
        targets.add(Path(os.environ["DFTHUB_OPT_STATUS_PATH"]).resolve())
    for path in targets:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        temporary.replace(path)


def run_optimization(solver, theta0):
    theta0 = np.asarray(theta0, dtype=np.float64)
    solver.ftol = OPTIMIZATION_FTOL
    solver.options = {**(solver.options or {}), "ftol": OPTIMIZATION_FTOL}
    report = {
        "status": "Running", "converged": False, "method": solver.method,
        "ftol": OPTIMIZATION_FTOL, "max_iterations": solver.maxiter,
        "started_at": time.time(),
    }
    save_status(report)
    print(f"Optimization: {solver.method}, ftol={OPTIMIZATION_FTOL:g}, maxiter={solver.maxiter}", flush=True)
    try:
        if theta0.ndim != 1 or not np.all(np.isfinite(theta0)):
            raise ValueError("Initial optimization parameters are not finite")
        initial_loss = float(solver.fun(theta0))
        if not math.isfinite(initial_loss):
            raise ValueError("Initial optimization objective is not finite")
        report["initial_objective"] = initial_loss
        save_status(report)
        result = solver.run(theta0)
        state = result.state
        params = np.asarray(result.params, dtype=np.float64)
        final_loss = float(solver.fun(params))
        gradient = np.asarray(solver.jac(params), dtype=np.float64)
        finite = math.isfinite(final_loss) and np.all(np.isfinite(params)) and np.all(np.isfinite(gradient))
        code = int(state.status)
        messages = {
            0: "Optimization terminated successfully",
            2: "More equality constraints than independent variables",
            3: "More than 3*n iterations in LSQ subproblem",
            4: "Inequality constraints incompatible",
            5: "Singular matrix E in LSQ subproblem",
            6: "Singular matrix C in LSQ subproblem",
            7: "Rank-deficient equality constraint subproblem",
            8: "Positive directional derivative for line search",
            9: "Iteration limit reached",
        }
        converged = bool(state.success) and code == 0 and bool(finite)
        report.update(
            status="Success" if converged else "Failed", converged=converged,
            status_code=code, termination_reason=messages.get(code, f"SLSQP status {code}"),
            iterations=int(state.iter_num),
            function_evaluations=int(state.num_fun_eval), gradient_evaluations=int(state.num_jac_eval),
            final_objective=final_loss if math.isfinite(final_loss) else None,
            objective_improvement=initial_loss - final_loss if math.isfinite(final_loss) else None,
            gradient_l2=float(np.linalg.norm(gradient)) if np.all(np.isfinite(gradient)) else None,
            gradient_max_abs=float(np.max(np.abs(gradient))) if np.all(np.isfinite(gradient)) else None,
            max_parameter_change=float(np.max(np.abs(params - theta0))) if np.all(np.isfinite(params)) else None,
        )
        if not converged:
            reason = report["termination_reason"] if finite else "Non-finite optimized parameters, objective or gradient"
            raise RuntimeError(f"Parameter optimization did not converge: {reason}")
        report.update(finished_at=time.time(), elapsed_seconds=time.time() - report["started_at"])
        save_status(report)
        print(f"Optimization converged: iterations={report['iterations']}, status={code}, "
              f"objective={initial_loss:.12g} -> {final_loss:.12g}, "
              f"gradient_max={report['gradient_max_abs']:.6g}", flush=True)
        return result
    except Exception as exc:
        report.update(status="Failed", converged=False, error=str(exc),
                      finished_at=time.time(), elapsed_seconds=time.time() - report["started_at"])
        save_status(report)
        raise
