import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from scipy.optimize import minimize

from dfthub.pipeline.optimization_runtime import run_optimization


class Solver:
    method = "SLSQP"

    def __init__(self, fun, jac, maxiter=200):
        self.fun = fun
        self.jac = jac
        self.maxiter = maxiter
        self.ftol = 1e-10
        self.options = {"ftol": self.ftol, "maxiter": maxiter}

    def run(self, theta0):
        result = minimize(
            self.fun,
            np.asarray(theta0, dtype=np.float64),
            jac=self.jac,
            method=self.method,
            options=self.options,
        )
        result.params = np.asarray(result.x, dtype=np.float64)
        result.state = SimpleNamespace(
            success=bool(result.success),
            status=int(result.status),
            iter_num=int(result.nit),
            num_fun_eval=int(result.nfev),
            num_jac_eval=int(result.njev),
        )
        return result


class ConvergenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dfthub-convergence-test-")
        self.root = Path(self.temp.name).resolve()
        self.previous_cwd = Path.cwd()
        os.chdir(self.root)
        self.environment = patch.dict(os.environ, {"DFTHUB_OPT_STATUS_PATH": str(self.root / "published.json")})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    def test_small_initial_improvement_does_not_stop_after_one_step(self):
        fun = lambda x: 1e-4 * np.sum((x - np.array([2.0, -3.0])) ** 2)
        jac = lambda x: 2e-4 * (x - np.array([2.0, -3.0]))
        result = run_optimization(Solver(fun, jac), np.zeros(2))
        np.testing.assert_allclose(result.params, [2.0, -3.0], atol=1e-5)
        report = json.loads((self.root / "published.json").read_text())
        self.assertEqual(report["ftol"], 1e-12)
        self.assertTrue(report["converged"])
        self.assertGreater(report["iterations"], 1)
        self.assertGreater(report["objective_improvement"], 0.001)
        self.assertEqual(report, json.loads((self.root / "OptimizationStatus.json").read_text()))

    def test_iteration_limit_is_a_failure_with_diagnostics(self):
        fun = lambda x: (1 - x[0]) ** 2 + 100 * (x[1] - x[0] ** 2) ** 2
        jac = lambda x: np.array([
            2 * (x[0] - 1) - 400 * x[0] * (x[1] - x[0] ** 2),
            200 * (x[1] - x[0] ** 2),
        ])
        with self.assertRaisesRegex(RuntimeError, "Iteration limit"):
            run_optimization(Solver(fun, jac, maxiter=1), np.array([-1.2, 1.0]))
        report = json.loads((self.root / "OptimizationStatus.json").read_text())
        self.assertEqual(report["status"], "Failed")
        self.assertFalse(report["converged"])
        self.assertEqual(report["status_code"], 9)
        self.assertIn("final_objective", report)
        self.assertIn("gradient_max_abs", report)

    def test_nonfinite_objective_is_recorded_as_failure(self):
        fun = lambda x: float("nan")
        jac = lambda x: np.zeros_like(x)
        with self.assertRaisesRegex(ValueError, "not finite"):
            run_optimization(Solver(fun, jac, maxiter=2), np.zeros(2))
        report = json.loads((self.root / "OptimizationStatus.json").read_text())
        self.assertEqual(report["status"], "Failed")
        self.assertFalse(report["converged"])

    def test_new_weight_and_inherited_templates_use_one_shared_policy(self):
        from dfthub.pipeline import opt_demo
        template = self.root / "template"
        (template / "Database_updated/fit").mkdir(parents=True)
        (template / "Database_updated/ref").mkdir()
        for name in ("dataset.py", "saver.py"):
            (template / name).write_text("# fixture\n")
        (template / "params.txt").write_text("\n".join(["0"] * 59))
        (template / "opt.py").write_text(
            "weight ={'INPUT_ref': 0.2}\n"
            "solver = object()\n"
            "res = solver.run(theta0)\n"
        )
        fit, ref = self.root / "INPUT", self.root / "INPUT_ref"
        fit.write_text("fixture descriptors")
        ref.write_text("fixture reference")
        with patch.object(opt_demo, "TMB11_DIR", template), patch.object(opt_demo, "DEMO_ROOT", self.root), patch.object(opt_demo, "native_cf22d_parameters", return_value={"coefficients": [0] * 59}):
            new = opt_demo.build_demo("new", fit, ref, 0.2, 10000)
            reweight = opt_demo.build_demo("weights", fit, ref, 0.1, 10000, all_weights={"INPUT_ref": 0.1})
            fork = opt_demo.build_demo("fork", fit, ref, 0.2, 10000, template_dir=new, initial_params=template / "params.txt")
            for path in (new, reweight, fork):
                source = (path / "opt.py").read_text()
                self.assertEqual(source.count("res = run_optimization(solver, theta0)"), 1)
                self.assertEqual(source.count("from optimization_runtime import run_optimization"), 1)
                self.assertNotIn("res = solver.run(theta0)", source)
                compile(source, str(path / "opt.py"), "exec")
                self.assertTrue((path / "optimization_runtime.py").is_file())


if __name__ == "__main__":
    unittest.main()
