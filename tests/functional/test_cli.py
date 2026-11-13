import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gaussian import UTILAM, UTILNZ, make_tree  # noqa: E402

from dfthub.functional.parameters import read_parameters  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PARAMETERS = ROOT / "Parameters"
HAS_PYSCF = importlib.util.find_spec("pyscf") is not None


def dfthub(*args, cwd=None):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-m", "dfthub.cli", *map(str, args)],
                          capture_output=True, text=True, cwd=cwd, env=env)


class ParamsCommandTests(unittest.TestCase):
    def test_check_and_show(self):
        result = dfthub("params", "check", PARAMETERS, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        info = json.loads(result.stdout)
        self.assertEqual(info["sha256"], read_parameters(PARAMETERS).sha256())
        shown = dfthub("params", "show", PARAMETERS)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("Cx(0,0,0)   _CC000  -1.8691297464873982e-01", shown.stdout)
        self.assertEqual(len(shown.stdout.splitlines()), 61)
        data = json.loads(dfthub("params", "show", PARAMETERS, "--json").stdout)
        self.assertEqual(len(data["libxc"]["HYB_MGGA_X_CF22D"]), 41)

    def test_invalid_file_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as temporary:
            bad = Path(temporary) / "Parameters"
            bad.write_text("Cx(0,0,0) = 1.0\n")
            result = dfthub("params", "check", bad)
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing 58 value(s)", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


class ExportCommandTests(unittest.TestCase):
    def test_export_to_file_and_stdout(self):
        from dfthub.functional import render
        params = read_parameters(PARAMETERS)
        with tempfile.TemporaryDirectory() as temporary:
            for program in ("pyscf", "gaussian", "orca", "psi4"):
                target = Path(temporary) / program
                result = dfthub("export", program, PARAMETERS, "-o", target)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(target.read_text(), render(program, params))
        result = dfthub("export", "gaussian", PARAMETERS, "--no-d3", "--keyword", "CF22D")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("%Chk=cf22d.chk\n#P CF22D/def2QZVP\n\n"))
        self.assertEqual(dfthub("export", "orca", PARAMETERS, "--keyword", "X").returncode, 1)


class G16CommandTests(unittest.TestCase):
    def test_dry_run_then_build_with_stub(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            top = make_tree(root)
            (top / "bsd/bldg16").write_text("#!/bin/bash\necho built > built.txt\n")
            (top / "bsd/bldg16").chmod(0o755)
            dry = dfthub("g16", "build", "--source", top, "--parameters", PARAMETERS, "--dry-run")
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertIn("59 line(s) would change", dry.stdout)
            self.assertEqual((top / "utilnz.F").read_text(), UTILNZ)
            self.assertEqual((top / "utilam.F").read_text(), UTILAM)

            build = dfthub("g16", "build", "--parameters", PARAMETERS, cwd=root)
            self.assertEqual(build.returncode, 0, build.stderr)
            output = root / "g16-opt"
            self.assertTrue((output / "built.txt").is_file())
            self.assertIn("IMHF = 581035", (output / "utilam.F").read_text())
            self.assertFalse(top.exists())

    def test_missing_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = dfthub("g16", "build", "--parameters", PARAMETERS, cwd=temporary)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Gaussian source directory not found", result.stderr)

    def test_legacy_script(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "dfthub_g16_builder.py"
            script.write_text((ROOT / "dfthub_g16_builder.py").read_text())
            (root / "Parameters").write_text(PARAMETERS.read_text())
            make_tree(root)
            result = subprocess.run([sys.executable, script, "--dry-run"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("deprecated", result.stderr)
            self.assertIn("would change", result.stdout)


class DoctorAndProcessCommandTests(unittest.TestCase):
    def test_doctor_formatting(self):
        from dfthub import cli
        with patch("dfthub.doctor.check", return_value={
            "engine": {"branch": "DFT", "commit": "e7cb7357", "pyscf": "2.14.0"},
            "errors": [],
        }):
            report = cli._format_doctor_report({
                "engine": {"branch": "DFT", "commit": "e7cb7357", "pyscf": "2.14.0"},
                "errors": [],
            })
        self.assertIn("Engine:\n  branch: DFT\n  commit: e7cb7357\n  pyscf: 2.14.0", report)
        self.assertIn("Status: OK (all checks passed)", report)

    def test_ps_and_kill_commands(self):
        result_ps = dfthub("ps")
        self.assertEqual(result_ps.returncode, 0, result_ps.stderr)
        result_ps_json = dfthub("ps", "--json")
        self.assertEqual(result_ps_json.returncode, 0, result_ps_json.stderr)
        self.assertIsInstance(json.loads(result_ps_json.stdout), list)

        result_kill_missing = dfthub("kill")
        self.assertEqual(result_kill_missing.returncode, 1)

        with tempfile.TemporaryDirectory() as temporary:
            proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
            try:
                fake_tasks = [{"pid": proc.pid, "output": str(Path(temporary).resolve()),
                               "scope": "optimization", "mode": "new"}]
                from dfthub import cli
                with patch("dfthub.processes.tasks", return_value=fake_tasks):
                    rc = cli.main(["ps"])
                    self.assertEqual(rc, 0)
                    rc_kill = cli.main(["kill", str(proc.pid)])
                    self.assertEqual(rc_kill, 0)
                proc.wait(timeout=5)
                self.assertIsNotNone(proc.returncode)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()


@unittest.skipUnless(HAS_PYSCF, "PySCF engine not installed")
class PySCFTests(unittest.TestCase):
    def test_register_sets_parameters(self):
        from pyscf import dft, gto
        from pyscf.dft import libxc
        from dfthub.functional.pyscf import apply_cf22d, register_cf22d
        params = read_parameters(PARAMETERS)
        mf = dft.RKS(gto.M(atom="H 0 0 0; H 0 0 0.74", basis="sto-3g", verbose=0))
        register_cf22d(mf, params, name="dfthub_test_cf22d", with_d3=False)
        self.assertEqual(mf.xc, "dfthub_test_cf22d")
        self.assertIs(mf.disp, False)
        self.assertIs(apply_cf22d, register_cf22d)
        self.assertAlmostEqual(libxc.hybrid_coeff(mf.xc), params.hf, places=14)

    def test_h2_reference_energy(self):
        from dfthub.functional.pyscf import run_demo
        try:
            import pyscf.dispersion  # noqa: F401
            with_d3 = True
        except ImportError:
            try:
                import dftd3.pyscf  # noqa: F401
                with_d3 = True
            except ImportError:
                with_d3 = False
        energy = run_demo(PARAMETERS, with_d3=with_d3, verbose=0)
        # README reference, RKS/def2-QZVP/grid 6; the D3 term for H2 is below 1e-10 Eh.
        self.assertAlmostEqual(energy, -1.16348600462391, delta=1e-8)


if __name__ == "__main__":
    unittest.main()
