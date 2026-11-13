"""Exports are compared byte for byte with tests/functional/golden.

After an intentional template change, regenerate the golden files with
DFTHUB_UPDATE_GOLDEN=1 python -m unittest discover -s tests/functional
and review the diff.
"""
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest

from dfthub.functional import DEFAULT_FILENAMES, PROGRAMS, render
from dfthub.functional.parameters import CF22DParameters, D3_ZERO, read_parameters

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).with_name("golden")
PARAMETERS = read_parameters(ROOT / "Parameters")


class GoldenTests(unittest.TestCase):
    def test_exports_match_golden_files(self):
        for program in PROGRAMS:
            for with_d3 in (True, False):
                name = DEFAULT_FILENAMES[program]
                if not with_d3:
                    stem, dot, suffix = name.rpartition(".")
                    name = f"{stem}_no_d3.{suffix}"
                text = render(program, PARAMETERS, with_d3=with_d3)
                path = GOLDEN / name
                if os.environ.get("DFTHUB_UPDATE_GOLDEN") == "1":
                    GOLDEN.mkdir(exist_ok=True)
                    path.write_text(text)
                with self.subTest(program=program, with_d3=with_d3):
                    self.assertEqual(text, path.read_text())


class PySCFScriptTests(unittest.TestCase):
    def test_script_is_valid_and_exact(self):
        text = render("pyscf", PARAMETERS)
        compile(text, "CF22D_optimized.py", "exec")
        rows = re.findall(r"^\s+(-?\d.*?),?$", text, re.MULTILINE)
        numbers = [float(value) for row in rows for value in row.split(",") if value.strip()]
        self.assertEqual(numbers, list(PARAMETERS.cx + PARAMETERS.cy + PARAMETERS.cz))
        self.assertIn(f"HF_COEFF = {PARAMETERS.hf!r}", text)
        self.assertIn("def register_cf22d_srp(mf, name=\"cf22d_srp\"):", text)
        self.assertIn("WITH_D3 = False", render("pyscf", PARAMETERS, with_d3=False))

    def test_web_generator_uses_same_template(self):
        try:
            from dfthub.pipeline.main import generate_demo_script
        except Exception as exc:  # pipeline imports need the full runtime
            self.skipTest(f"pipeline unavailable: {exc}")
        from dfthub.functional.pyscf import render_script
        with tempfile.TemporaryDirectory() as temporary:
            params = Path(temporary) / "NEW-params.txt"
            params.write_text("\n".join(f"{v:.17g}" for v in PARAMETERS.vector()) + "\n")
            output = Path(temporary) / "CF22D_optimized.py"
            generate_demo_script(params, output, dataset_name="Demo")
            self.assertEqual(output.read_text(), render_script(PARAMETERS, dataset_name="Demo"))
            params.write_text("1 2 3\n")
            generate_demo_script(params, Path(temporary) / "skipped.py")
            self.assertFalse((Path(temporary) / "skipped.py").exists())


class Psi4Tests(unittest.TestCase):
    def load(self, with_d3=True):
        fake = types.ModuleType("psi4")
        namespace = {}
        sys.modules["psi4"] = fake
        try:
            exec(compile(render("psi4", PARAMETERS, with_d3=with_d3), "cf22d_psi4.py", "exec"), namespace)
        finally:
            del sys.modules["psi4"]
        return namespace["CF22D_DFTHUB"]

    def test_dictionary(self):
        func = self.load()
        x = func["x_functionals"]["HYB_MGGA_X_CF22D"]
        self.assertIs(x["use_libxc"], False)
        self.assertEqual(x["tweak"], PARAMETERS.libxc_x_named())
        self.assertEqual(func["x_hf"], {"alpha": PARAMETERS.hf})
        self.assertEqual(func["c_functionals"]["MGGA_C_CF22D"]["tweak"], PARAMETERS.libxc_c_named())
        # Psi4 requires exactly the d3zero2b parameter names.
        self.assertEqual(func["dispersion"]["type"], "d3zero2b")
        self.assertEqual(sorted(func["dispersion"]["params"]), ["alpha6", "s6", "s8", "sr6", "sr8"])
        self.assertEqual(func["dispersion"]["params"]["sr6"], D3_ZERO["rs6"])
        self.assertTrue(func["description"].startswith("    ") and func["description"].endswith("\n"))
        self.assertNotIn("dispersion", self.load(with_d3=False))


class OrcaTests(unittest.TestCase):
    def test_parameters_and_dispersion(self):
        text = render("orca", PARAMETERS)
        x = dict(re.findall(r'^\s+ExtParamX "(\w+)"\s+(\S+)$', text, re.MULTILINE))
        c = dict(re.findall(r'^\s+ExtParamC "(\w+)"\s+(\S+)$', text, re.MULTILINE))
        self.assertEqual({k: float(v) for k, v in x.items()}, PARAMETERS.libxc_x_named())
        self.assertEqual({k: float(v) for k, v in c.items()}, PARAMETERS.libxc_c_named())
        self.assertIn("  Exchange    hyb_mgga_x_cf22d\n  Correlation mgga_c_cf22d\n", text)
        self.assertIn("! RKS def2-QZVP DefGrid3 D3ZERO\n", text)
        self.assertIn("  D3RS6    1.53\n", text)
        no_d3 = render("orca", PARAMETERS, with_d3=False, basis="def2-TZVP")
        self.assertIn("! RKS def2-TZVP DefGrid3\n", no_d3)
        self.assertNotIn("D3", no_d3)

    def test_distinct_sets_give_distinct_inputs(self):
        other = CF22DParameters.from_vector([v * 1.01 for v in PARAMETERS.vector()])
        self.assertNotEqual(render("orca", other), render("orca", PARAMETERS))


if __name__ == "__main__":
    unittest.main()
