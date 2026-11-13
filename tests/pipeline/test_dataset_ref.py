import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
OPTIMIZER_DIR = SRC_DIR / "dfthub" / "resources" / "optimizer"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(OPTIMIZER_DIR) not in sys.path:
    sys.path.insert(0, str(OPTIMIZER_DIR))

from dataset import CFXXD_Train_Data_Set  # noqa: E402
from dfthub.archives import extract_geometry_archive  # noqa: E402


def _legacy_read_ref_file(fp: str) -> list:
    """Reference implementation of the original __read_ref_file__ for backward-compatibility checks."""
    result = []
    support_n_col = [3, 5, 6, 7, 8, 9, 10, 11, 12, 15, 16, 25, 43, 85, 13, 17]
    with open(fp, "r") as handle:
        for line in handle.readlines():
            out = {}
            parts = line.split()
            n_col = len(parts)
            out["job_type"] = n_col
            out["name"] = []
            out["ratio_s"] = []
            out["ref_s"] = []
            out["ratioo"] = 1.0
            out["has_ratioo"] = 627.509
            if n_col % 2 == 0 and n_col in support_n_col:
                out["name"].extend([parts[i] for i in range(1, n_col - 1, 2)])
                out["ratio_s"].extend([np.float64(parts[i]) for i in range(0, n_col - 2, 2)])
                out["ref_s"].append(np.float64(parts[n_col - 2]))
                out["ratioo"] = np.float64(parts[n_col - 1])
                out["has_ratioo"] = 1.0
            elif n_col % 2 != 0 and n_col in support_n_col:
                out["name"].extend([parts[i] for i in range(1, n_col - 1, 2)])
                out["ratio_s"].extend([np.float64(parts[i]) for i in range(0, n_col - 2, 2)])
                out["ref_s"].append(np.float64(parts[n_col - 1]))
            else:
                continue
            out["ref_s"] = np.array(out["ref_s"])
            out["ratio_s"] = np.array(out["ratio_s"])
            result.append(out)
    return result


def _load_file_api_module():
    """Import dfthub.api.file_api, providing lightweight stubs if Flask/psutil are absent in minimal envs."""
    try:
        from dfthub.api import file_api
        return file_api
    except ModuleNotFoundError:
        saved = {}
        stubs = {}

        class _DummyBlueprint:
            def __init__(self, *args, **kwargs):
                pass

            def route(self, *args, **kwargs):
                return lambda fn: fn

            def get(self, *args, **kwargs):
                return lambda fn: fn

            def post(self, *args, **kwargs):
                return lambda fn: fn

            def put(self, *args, **kwargs):
                return lambda fn: fn

            def delete(self, *args, **kwargs):
                return lambda fn: fn

            def doc(self, *args, **kwargs):
                return lambda fn: fn

            def input(self, *args, **kwargs):
                return lambda fn: fn

        class _DummyApp(_DummyBlueprint):
            def register_blueprint(self, *args, **kwargs):
                pass

        apiflask_mod = types.ModuleType("apiflask")
        apiflask_mod.APIBlueprint = _DummyBlueprint
        apiflask_mod.APIFlask = _DummyApp
        apiflask_mod.Schema = object
        apiflask_mod.abort = lambda code, message="": (_ for _ in ()).throw(RuntimeError(f"{code}: {message}"))

        fields_mod = types.ModuleType("apiflask.fields")
        for attr in ("File", "String", "Integer", "List", "Boolean"):
            setattr(fields_mod, attr, lambda *a, **k: None)

        validators_mod = types.ModuleType("apiflask.validators")
        validators_mod.OneOf = lambda *a, **k: None

        flask_mod = types.ModuleType("flask")
        flask_mod.current_app = types.SimpleNamespace(extensions={})
        flask_mod.g = types.SimpleNamespace(current_user={"username": "testuser"})
        flask_mod.has_app_context = lambda: False
        flask_mod.send_file = lambda *a, **k: None

        werkzeug_mod = types.ModuleType("werkzeug")
        werkzeug_mod.run_simple = lambda *a, **k: None
        serving_mod = types.ModuleType("werkzeug.serving")
        serving_mod.run_simple = lambda *a, **k: None
        utils_mod = types.ModuleType("werkzeug.utils")
        utils_mod.secure_filename = lambda s: s

        auth_mod = types.ModuleType("dfthub.api.auth")
        auth_mod.authenticate_request = lambda: None
        auth_mod.login_required = lambda fn: fn

        config_mod = types.ModuleType("dfthub.api.config")
        config_mod.DATA_DIR = Path(tempfile.gettempdir())

        psutil_mod = types.ModuleType("psutil")

        stubs = {
            "apiflask": apiflask_mod,
            "apiflask.fields": fields_mod,
            "apiflask.validators": validators_mod,
            "flask": flask_mod,
            "werkzeug": werkzeug_mod,
            "werkzeug.serving": serving_mod,
            "werkzeug.utils": utils_mod,
            "dfthub.api.auth": auth_mod,
            "dfthub.api.config": config_mod,
            "psutil": psutil_mod,
        }
        for name, mod in stubs.items():
            saved[name] = sys.modules.get(name)
            sys.modules[name] = mod
        try:
            spec = importlib.util.spec_from_file_location(
                "dfthub.api.file_api",
                SRC_DIR / "dfthub" / "api" / "file_api.py",
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        finally:
            for name, original in saved.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original


class DatasetRefParserTests(unittest.TestCase):
    def setUp(self):
        self.reader = object.__new__(CFXXD_Train_Data_Set)

    def test_even_columns_4_14_18_and_arbitrary_even(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref_path = Path(tmp) / "even.ref"
            # 4 cols (1 molecule), 14 cols (6 molecules), 18 cols (8 molecules)
            line_4 = "1 mol_1 -0.500000 1.0"
            line_14 = " ".join([f"{i} m_{i}" for i in range(1, 7)]) + " 12.345 2.0"
            line_18 = " ".join([f"{-i} x_{i}" for i in range(1, 9)]) + " -45.678 1.0"
            ref_path.write_text("\n".join([line_4, line_14, line_18]) + "\n")

            parsed = self.reader.__read_ref_file__(str(ref_path), Ignore_error=False)
            self.assertEqual(len(parsed), 3)

            # 4 columns
            self.assertEqual(parsed[0]["job_type"], 4)
            self.assertEqual(parsed[0]["name"], ["mol_1"])
            np.testing.assert_allclose(parsed[0]["ratio_s"], np.array([1.0]))
            np.testing.assert_allclose(parsed[0]["ref_s"], np.array([-0.5]))
            self.assertAlmostEqual(parsed[0]["ratioo"], 1.0)
            self.assertAlmostEqual(parsed[0]["has_ratioo"], 1.0)

            # 14 columns
            self.assertEqual(parsed[1]["job_type"], 14)
            self.assertEqual(parsed[1]["name"], [f"m_{i}" for i in range(1, 7)])
            np.testing.assert_allclose(parsed[1]["ratio_s"], np.arange(1, 7, dtype=np.float64))
            np.testing.assert_allclose(parsed[1]["ref_s"], np.array([12.345]))
            self.assertAlmostEqual(parsed[1]["ratioo"], 2.0)
            self.assertAlmostEqual(parsed[1]["has_ratioo"], 1.0)

            # 18 columns
            self.assertEqual(parsed[2]["job_type"], 18)
            self.assertEqual(parsed[2]["name"], [f"x_{i}" for i in range(1, 9)])
            np.testing.assert_allclose(parsed[2]["ratio_s"], -np.arange(1, 9, dtype=np.float64))
            np.testing.assert_allclose(parsed[2]["ref_s"], np.array([-45.678]))
            self.assertAlmostEqual(parsed[2]["ratioo"], 1.0)
            self.assertAlmostEqual(parsed[2]["has_ratioo"], 1.0)

    def test_odd_columns_3_5_19_use_default_hartree_to_kcal_scale(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref_path = Path(tmp) / "odd.ref"
            line_3 = "1 mol_a -0.1000"
            line_5 = "1 mol_a -1 mol_b 0.0500"
            line_19 = " ".join([f"1 p_{i}" for i in range(1, 10)]) + " -1.2345"
            ref_path.write_text("\n".join([line_3, line_5, line_19]) + "\n")

            parsed = self.reader.__read_ref_file__(str(ref_path), Ignore_error=False)
            self.assertEqual(len(parsed), 3)

            self.assertEqual(parsed[0]["job_type"], 3)
            self.assertEqual(parsed[0]["name"], ["mol_a"])
            np.testing.assert_allclose(parsed[0]["ratio_s"], np.array([1.0]))
            np.testing.assert_allclose(parsed[0]["ref_s"], np.array([-0.1]))
            self.assertAlmostEqual(parsed[0]["ratioo"], 1.0)
            self.assertAlmostEqual(parsed[0]["has_ratioo"], 627.509)

            self.assertEqual(parsed[1]["job_type"], 5)
            self.assertEqual(parsed[1]["name"], ["mol_a", "mol_b"])
            np.testing.assert_allclose(parsed[1]["ratio_s"], np.array([1.0, -1.0]))
            np.testing.assert_allclose(parsed[1]["ref_s"], np.array([0.05]))
            self.assertAlmostEqual(parsed[1]["ratioo"], 1.0)
            self.assertAlmostEqual(parsed[1]["has_ratioo"], 627.509)

            self.assertEqual(parsed[2]["job_type"], 19)
            self.assertEqual(parsed[2]["name"], [f"p_{i}" for i in range(1, 10)])
            np.testing.assert_allclose(parsed[2]["ratio_s"], np.ones(9, dtype=np.float64))
            np.testing.assert_allclose(parsed[2]["ref_s"], np.array([-1.2345]))
            self.assertAlmostEqual(parsed[2]["ratioo"], 1.0)
            self.assertAlmostEqual(parsed[2]["has_ratioo"], 627.509)

    def test_error_handling_for_short_lines_and_invalid_floats(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_col_path = Path(tmp) / "too_short.ref"
            bad_col_path.write_text("1 mol_a 0.5 1.0\nonly_two cols\n1 mol_b -0.2 1.0\n")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                res = self.reader.__read_ref_file__(str(bad_col_path), Ignore_error=True)
            self.assertEqual(len(res), 2)
            self.assertIn("too_short.ref", buf.getvalue())
            self.assertIn("line 2", buf.getvalue())

            with self.assertRaises(ValueError) as ctx:
                self.reader.__read_ref_file__(str(bad_col_path), Ignore_error=False)
            self.assertIn("too_short.ref", str(ctx.exception))
            self.assertIn("line 2", str(ctx.exception))

            bad_float_path = Path(tmp) / "bad_float.ref"
            bad_float_path.write_text("1 mol_a 0.5 1.0\n1 mol_a -1 mol_b not_a_number 1.0\n")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                res = self.reader.__read_ref_file__(str(bad_float_path), Ignore_error=True)
            self.assertEqual(len(res), 1)
            self.assertIn("bad_float.ref", buf.getvalue())
            self.assertIn("line 2", buf.getvalue())

            with self.assertRaises(ValueError) as ctx:
                self.reader.__read_ref_file__(str(bad_float_path), Ignore_error=False)
            self.assertIn("bad_float.ref", str(ctx.exception))
            self.assertIn("line 2", str(ctx.exception))

    def test_100_percent_backward_compatibility_with_all_builtin_ref_files(self):
        for subdir in ("Database_updated/ref", "Database2/ref"):
            ref_dir = OPTIMIZER_DIR / subdir
            ref_files = sorted(p for p in ref_dir.iterdir() if p.is_file())
            self.assertGreaterEqual(len(ref_files), 41)
            for ref_file in ref_files:
                expected = _legacy_read_ref_file(str(ref_file))
                actual = self.reader.__read_ref_file__(str(ref_file), Ignore_error=False)
                self.assertEqual(len(actual), len(expected), f"Mismatch length in {ref_file}")
                for row_a, row_e in zip(actual, expected):
                    self.assertEqual(row_a["job_type"], row_e["job_type"])
                    self.assertEqual(row_a["name"], row_e["name"])
                    self.assertEqual(row_a["ratioo"], row_e["ratioo"])
                    self.assertEqual(row_a["has_ratioo"], row_e["has_ratioo"])
                    np.testing.assert_array_equal(row_a["ratio_s"], row_e["ratio_s"])
                    np.testing.assert_array_equal(row_a["ref_s"], row_e["ref_s"])

    def test_train_dataset_integration_with_4_14_18_col_reactions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fit_dir = root / "fit"
            ref_dir = root / "ref"
            fit_dir.mkdir()
            ref_dir.mkdir()

            # Create 8 molecules in fit/CUSTOM
            fit_lines = []
            for idx in range(1, 9):
                vals = " ".join(f"{0.01 * idx:.6f}" for _ in range(62))
                fit_lines.append(f"mol_{idx} {vals}")
            (fit_dir / "CUSTOM").write_text("\n".join(fit_lines) + "\n")

            # Create ref/CUSTOM_ref with 4, 14, and 18 columns
            line_4 = "1 mol_1 -0.5 1.0"
            line_14 = " ".join(f"1 mol_{i}" for i in range(1, 7)) + " 2.5 1.0"
            line_18 = " ".join(f"1 mol_{i}" for i in range(1, 9)) + " 3.5 1.0"
            (ref_dir / "CUSTOM_ref").write_text("\n".join([line_4, line_14, line_18]) + "\n")

            ds = CFXXD_Train_Data_Set(
                database={"CUSTOM": ["CUSTOM_ref"]},
                ref_root_path=str(ref_dir),
                fit_root_path=str(fit_dir),
                cut=[3, 7, 42],
                weight={"CUSTOM_ref": 0.02},
            )
            # Group 0 (<=3 molecules): 1 reaction (4 cols -> 1 molecule)
            # Group 1 (<=7 molecules): 1 reaction (14 cols -> 6 molecules)
            # Group 2 (<=42 molecules): 1 reaction (18 cols -> 8 molecules)
            self.assertEqual(ds.fit_data[0].shape[0], 1)
            self.assertEqual(ds.fit_data[1].shape[0], 1)
            self.assertEqual(ds.fit_data[2].shape[0], 1)


class FileApiTotalMueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.file_api = _load_file_api_module()

    def test_prefers_new_total_mue_over_trailing_total_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            mue_file = Path(tmp) / "Mue"
            mue_file.write_text(
                "------------SUMMARY-------------\n"
                "input\t0.4215\n"
                "BH76RC\t1.1234\n"
                "new_total_mue:1.5823456\n"
                "\n"
                "------------LOSS----------------\n"
                "Weighted MUE sum:\t235.1200\n"
                "Regularization (0.01*(a+b+c)):\t0.2144\n"
                "Total loss:\t235.3344\n"
            )
            self.assertEqual(
                self.file_api._read_total_mue(mue_file),
                "new_total_mue:1.5823456",
            )

    def test_fallback_to_last_non_empty_line_when_new_total_mue_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            mue_file = Path(tmp) / "Mue"
            mue_file.write_text(
                "------------SUMMARY-------------\n"
                "test_input\t0.7500\n"
                "\n\n"
            )
            self.assertEqual(
                self.file_api._read_total_mue(mue_file),
                "test_input\t0.7500",
            )

    def test_missing_or_empty_mue_returns_no_mue(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "Mue"
            self.assertEqual(self.file_api._read_total_mue(missing), "No Mue")
            missing.write_text("   \n\t\n")
            self.assertEqual(self.file_api._read_total_mue(missing), "No Mue")

    def test_get_file_list_returns_new_total_mue_in_folder_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp).resolve()
            run_dir = data_root / "Work" / "testuser" / "job1" / "output" / "weight_0"
            run_dir.mkdir(parents=True)
            (run_dir / "Mue").write_text(
                "------------SUMMARY-------------\n"
                "input\t0.3125\n"
                "new_total_mue:1.4200\n"
                "\n"
                "------------LOSS----------------\n"
                "Total loss:\t235.3344\n"
            )
            old_data_dir = self.file_api.DATA_DIR
            old_activity = self.file_api._task_activity
            self.file_api.DATA_DIR = data_root
            self.file_api._task_activity = lambda: {}
            self.file_api.g.current_user = {"username": "testuser"}
            try:
                resp = self.file_api.get_file_list(
                    {
                        "file_dir": "Work/testuser/job1/output",
                        "file_filter": "*",
                        "file_or_folder": "folder",
                    }
                )
                self.assertEqual(len(resp["result"]), 1)
                self.assertEqual(resp["result"][0]["name"], "weight_0")
                self.assertEqual(resp["result"][0]["total_mue"], "new_total_mue:1.4200")
            finally:
                self.file_api.DATA_DIR = old_data_dir
                self.file_api._task_activity = old_activity


class TemplateIntegrityTests(unittest.TestCase):
    def test_template_archive_and_ref_are_stoichiometrically_valid(self):
        template_dir = SRC_DIR / "dfthub" / "resources" / "template" / "dft_DFThub_template"
        readme_path = template_dir / "README.md"
        ref_path = template_dir / "upload" / "YourDatabaseName.ref"
        tgz_path = template_dir / "upload" / "YourDatabaseName.tgz"

        readme_text = readme_path.read_text(encoding="utf-8")
        self.assertIn("<charge> <multiplicity> [basis]", readme_text)
        self.assertIn("kcal/mol", readme_text)
        self.assertIn("init_weight.csv", readme_text)

        reader = object.__new__(CFXXD_Train_Data_Set)
        parsed_ref = reader.__read_ref_file__(str(ref_path), Ignore_error=False)
        self.assertGreaterEqual(len(parsed_ref), 1)

        with tempfile.TemporaryDirectory() as tmp:
            extract_geometry_archive(tgz_path, tmp)
            xyz_files = {p.stem: p for p in Path(tmp).rglob("*.xyz")}
            for entry in parsed_ref:
                atom_balance = {}
                charge_balance = 0.0
                for coeff, mol_name in zip(entry["ratio_s"], entry["name"]):
                    self.assertIn(mol_name, xyz_files, f"Missing {mol_name}.xyz in YourDatabaseName.tgz")
                    lines = xyz_files[mol_name].read_text(encoding="utf-8").strip().splitlines()
                    natom = int(lines[0].split()[0])
                    header = lines[1].split()
                    charge = int(header[0])
                    mult = int(header[1])
                    self.assertGreaterEqual(mult, 1)
                    self.assertEqual(len(lines) - 2, natom)
                    charge_balance += coeff * charge
                    for atom_line in lines[2 : 2 + natom]:
                        elem = atom_line.split()[0]
                        atom_balance[elem] = atom_balance.get(elem, 0.0) + coeff
                self.assertAlmostEqual(charge_balance, 0.0)
                for elem, net_count in atom_balance.items():
                    self.assertAlmostEqual(
                        net_count,
                        0.0,
                        msg=f"Element {elem} is not stoichiometrically balanced in template reaction",
                    )


if __name__ == "__main__":
    unittest.main()
