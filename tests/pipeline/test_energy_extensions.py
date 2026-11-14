import json
import math
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from dfthub.functional.parameters import ORIGINAL
from dfthub.functional.pyscf import write_script
from dfthub.pipeline.energy_extensions import (
    EnergyTaskOptions,
    HARTREE_TO_KCAL,
    evaluate_molecule_energy,
    list_supported_solvents,
    resolve_solvent_entry,
    solution_standard_state_correction_hartree,
)


class EnergyExtensionsTests(unittest.TestCase):
    def test_options_normalization_and_validation(self):
        opts = EnergyTaskOptions.from_dict(
            {
                "basis": "STO-3G",
                "grid_level": 5,
                "with_d3": False,
                "solvent_model": "SMD",
                "solvent_name": "Water",
                "optimize_geometry": True,
                "calc_thermo": True,
                "temperature_k": 310.15,
                "pressure_pa": 100000.0,
                "vib_model": "qrrho-full",
                "qrrho_freq0": 80.0,
                "freq_scale": 0.985,
                "solution_standard_state": True,
            }
        )
        self.assertEqual(opts.basis, "sto-3g")
        self.assertEqual(opts.grid_level, 5)
        self.assertFalse(opts.with_d3)
        self.assertEqual(opts.solvent_model, "smd")
        self.assertEqual(opts.solvent_name, "water")
        self.assertTrue(opts.optimize_geometry)
        self.assertTrue(opts.calc_thermo)
        self.assertAlmostEqual(opts.temperature_k, 310.15)
        self.assertAlmostEqual(opts.pressure_pa, 100000.0)
        self.assertEqual(opts.vib_model, "qrrho-full")

        with self.assertRaises(ValueError):
            EnergyTaskOptions(solvent_model="invalid-model").normalized()
        with self.assertRaises(ValueError):
            EnergyTaskOptions(solvent_model="ief-pcm", solvent_eps=0.5).normalized()
        with self.assertRaises(ValueError):
            EnergyTaskOptions(temperature_k=-10.0).normalized()

    def test_solvent_database_resolution(self):
        solvents = list_supported_solvents()
        self.assertGreaterEqual(len(solvents), 26)
        canonical, eps = resolve_solvent_entry("Water")
        self.assertEqual(canonical, "water")
        self.assertAlmostEqual(eps, 78.3553, places=3)

    def test_solution_standard_state_correction_at_298k_1atm(self):
        dg_eh = solution_standard_state_correction_hartree(298.15, 101325.0)
        dg_kcal = dg_eh * HARTREE_TO_KCAL
        # RT ln(24.465 L / 1 L) at 298.15 K is +1.894 kcal/mol
        self.assertAlmostEqual(dg_kcal, 1.894, places=2)

    def test_evaluate_molecule_smd_and_thermochemistry(self):
        with tempfile.TemporaryDirectory(prefix="dfthub-energy-ext-") as tmp:
            root = Path(tmp)
            cf22d = write_script(ORIGINAL, root / "CF22D_optimized.py")
            xyz = root / "H2.xyz"
            xyz.write_text("2\n0 1\nH 0.0 0.0 0.0\nH 0.0 0.0 0.76\n")
            opts = EnergyTaskOptions(
                basis="sto-3g",
                grid_level=4,
                with_d3=True,
                solvent_model="smd",
                solvent_name="water",
                optimize_geometry=True,
                calc_thermo=True,
                temperature_k=298.15,
                pressure_pa=101325.0,
                vib_model="qrrho-grimme",
                solution_standard_state=True,
            ).normalized()
            result = evaluate_molecule_energy(
                xyz_path=xyz,
                functional_path=str(cf22d),
                options=opts,
                stage_dir=root / "stage",
                name="H2",
                threads=2,
            )
            self.assertEqual(result["status"], "ok")
            self.assertTrue(math.isfinite(result["energy_hartree"]))
            self.assertIsNotNone(result["e_solvent_hartree"])
            self.assertIsNotNone(result["e_cds_hartree"])
            self.assertTrue(result["opt_converged"])
            self.assertIsNotNone(result["g_tot_hartree"])
            self.assertIsNotNone(result["h_tot_hartree"])
            self.assertIsNotNone(result["zpe_hartree"])
            self.assertEqual(result["imaginary_count"], 0)
            self.assertTrue((root / "stage" / "H2.opt.xyz").is_file())

    def test_run_user_energy_cli_end_to_end(self):
        with tempfile.TemporaryDirectory(prefix="dfthub-run-user-energy-") as tmp:
            root = Path(tmp)
            cf22d = write_script(ORIGINAL, root / "CF22D_optimized.py")
            xyz_dir = root / "xyz"
            xyz_dir.mkdir()
            (xyz_dir / "H2.xyz").write_text("2\n0 1\nH 0.0 0.0 0.0\nH 0.0 0.0 0.74\n")
            archive = root / "H2_set.tgz"
            with tarfile.open(archive, "w:gz") as tf:
                tf.add(xyz_dir / "H2.xyz", arcname="H2.xyz")
            out_dir = root / "output" / "weight_0" / "energy_input" / "task_1"
            out_dir.mkdir(parents=True)
            cfg = out_dir / "energy_config.json"
            cfg.write_text(
                json.dumps(
                    {
                        "basis": "sto-3g",
                        "grid_level": 4,
                        "with_d3": True,
                        "solvent_model": "ief-pcm",
                        "solvent_name": "acetonitrile",
                        "optimize_geometry": False,
                        "calc_thermo": True,
                        "temperature_k": 298.15,
                        "pressure_pa": 101325.0,
                        "vib_model": "qrrho-grimme",
                        "solution_standard_state": True,
                    }
                )
            )
            cmd = [
                sys.executable,
                "-m",
                "dfthub.pipeline.run_user_energy",
                "--cf22d-optimized",
                str(cf22d),
                "--output",
                str(out_dir),
                "--user-xyz",
                str(archive),
                "--config",
                str(cfg),
                "--cores",
                "2",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)
            res_file = out_dir / "SinglePointResults.energy.json"
            self.assertTrue(res_file.is_file())
            # Also mirrored to parent Run output directory
            self.assertTrue((root / "output" / "weight_0" / "SinglePointResults.energy.json").is_file())
            payload = json.loads(res_file.read_text())
            self.assertTrue(payload["complete"])
            self.assertEqual(payload["solvation"]["model"], "ief-pcm")
            self.assertTrue(payload["calc_thermo"])
            mol_row = payload["molecularEnergies"][0]
            self.assertEqual(mol_row["name"], "H2")
            self.assertEqual(mol_row["status"], "ok")
            self.assertIsNotNone(mol_row.get("g_tot_hartree"))
            self.assertIsNotNone(mol_row.get("e_solvent_hartree"))


if __name__ == "__main__":
    unittest.main()
