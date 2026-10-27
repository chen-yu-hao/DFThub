import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch

import numpy as np
from dfthub.pipeline import run_ame418_srp as runner
from dfthub.pipeline.refinement import write_json, correct_input_energies


class DescriptorScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dfthub-descriptors-")
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        initial = self.output / "weight_0" / "work"
        initial.mkdir(parents=True)
        (initial / "H.pychk").write_bytes(b"fixture checkpoint")
        self.functional = self.output / "CF22D_optimized.py"
        self.functional.write_text("# fixture")
        self.ref = self.output / "INPUT_ref"
        self.ref.write_text("1 H -0.5\n")
        self.xyz = self.root / "Input.tgz"
        self.xyz.write_bytes(b"fixture")
        self.parent_row = np.r_[np.zeros(60), -0.0123456789, 0.125]
        (self.output / "INPUT").write_text("H " + " ".join(map(str, self.parent_row)) + "\n")
        (self.output / "weight.csv").write_text("weight fixture")
        (self.output / "NEW-params.txt").write_text("\n".join(["1"] * 59))
        self.stage = self.root / "staged"
        self.stage.mkdir()
        (self.root / "H.xyz").write_text("# fixture geometry\n")
        (self.root / "H.py").write_text("# fixture molecule\n")
        (self.root / "H.chk").write_bytes(b"fixture checkpoint")
        self.job = runner.Job(self.root / "H.xyz", self.root / "H.xyz", "Input", "Input", "H", self.stage, self.stage / "H.py", self.stage / "H.chk", self.stage / "H.out", 1)
        self.grids = []

    def tearDown(self):
        self.temp.cleanup()

    def run_molecule(self, job, grid, *args):
        self.grids.append(grid)
        job.stage_out.write_text("FINAL ENERGY (Hartree): -0.5\n")
        np.save(job.stage_chk.with_suffix(".desc.npy"), np.ones(62))
        write_json(job.stage_chk.with_suffix(".desc.json"), {"converged": True, "grid_level": grid})
        return 0, -0.5, 0.01

    def invoke(self, scope, flags=()):
        argv = ["runner", "--scope", scope, "--cf22d-optimized", str(self.functional), "--output", str(self.output), "--cores", "1", "--no-pin"]
        if scope == "input":
            argv += ["--user-xyz", str(self.xyz), "--user-ref", str(self.ref)]
        with patch.object(sys, "argv", argv + list(flags)), contextlib.redirect_stdout(io.StringIO()):
            runner.main()

    def test_input_defaults_to_six_and_preserves_density_independent_columns(self):
        other = self.output / "SinglePointResults.ame418.json"
        other.write_text('{"keep":true}')
        with patch.object(runner, "discover_user_jobs", return_value=[self.job]), patch.object(runner, "run_user_job", side_effect=self.run_molecule), patch.object(runner, "discover", side_effect=AssertionError("AME418 discovery")):
            self.invoke("input")
        self.assertEqual(self.grids, [6])
        ready = json.loads((self.output / "InputDescriptors.json").read_text())
        row = np.loadtxt(self.output / "input_srp" / ready["id"] / "INPUT", usecols=range(1, 63))
        np.testing.assert_array_equal(row[60:], self.parent_row[60:])
        np.testing.assert_array_equal(row[:60], np.ones(60))
        self.assertEqual(other.read_text(), '{"keep":true}')
        result = json.loads((self.output / "SinglePointResults.input.json").read_text())
        self.assertEqual(result["descriptor_snapshot_id"], ready["id"])
        self.assertEqual(result["molecular_energies"]["H"]["d3_hartree"], self.parent_row[60])
        self.assertEqual(result["molecular_energies"]["H"]["energy_shift_kcal_mol"], self.parent_row[61])
        expected_error = abs(self.parent_row[60] * runner.HARTREE_TO_KCAL + self.parent_row[61])
        self.assertAlmostEqual(result["targetMue"], expected_error, places=4)
        self.assertEqual(result["corrections_sha256"], ready["corrections_sha256"])
        self.assertTrue(result["trainingComplete"])
        self.assertIsNone(result["testComplete"])
        self.assertTrue(result["evaluationComplete"])

    def test_d3_is_inherited_across_density_updates_and_applied_once(self):
        original, detail, digest = correct_input_energies({"H": -0.5}, self.output / "INPUT")
        row = self.parent_row.copy()
        row[:60] = 2.0
        (self.output / "fork-INPUT").write_text("H " + " ".join(map(str, row)) + "\n")
        updated, updated_detail, updated_digest = correct_input_energies({"H": -0.6}, self.output / "fork-INPUT")
        self.assertEqual(updated_digest, digest)
        self.assertEqual(updated_detail["H"]["d3_hartree"], detail["H"]["d3_hartree"])
        self.assertAlmostEqual(updated["H"] - original["H"], -0.1, places=12)
        self.assertEqual(updated["H"], -0.6 + row[60] + row[61] / runner.HARTREE_TO_KCAL)

    def test_explicit_grid_override_is_recorded(self):
        with patch.object(runner, "discover_user_jobs", return_value=[self.job]), patch.object(runner, "run_user_job", side_effect=self.run_molecule):
            self.invoke("input", ["--grid", "4"])
        self.assertEqual(self.grids, [4])
        self.assertEqual(json.loads((self.output / "InputDescriptors.json").read_text())["grid_level"], 4)

    def test_ame418_defaults_to_five_and_does_not_prepare_input(self):
        with patch.object(runner, "discover", return_value=([self.job], [])), patch.object(runner, "run_one", side_effect=self.run_molecule), patch.object(runner, "compute_errors", return_value=([], 0, [{"name": "AE17", "mue": 0}])), patch.object(runner, "prepare_input_snapshot", side_effect=AssertionError("Input preparation")):
            self.invoke("ame418")
        self.assertEqual(self.grids, [5])
        self.assertFalse((self.output / "InputDescriptors.json").exists())

    def test_failed_scf_never_reuses_stale_energy_or_publishes_descriptors(self):
        self.run_molecule(self.job, 6)
        with patch.object(runner, "discover_user_jobs", return_value=[self.job]), patch.object(runner, "run_user_job", return_value=(1, -0.5, 0)), self.assertRaises(SystemExit):
            self.invoke("input", ["--force"])
        self.assertFalse((self.output / "InputDescriptors.json").exists())

    def test_nonfinite_descriptors_never_publish_ready_snapshot(self):
        def invalid(*args):
            result = self.run_molecule(*args)
            np.save(self.job.stage_chk.with_suffix(".desc.npy"), np.full(62, np.nan))
            return result
        with patch.object(runner, "discover_user_jobs", return_value=[self.job]), patch.object(runner, "run_user_job", side_effect=invalid), self.assertRaises(ValueError):
            self.invoke("input")
        self.assertFalse((self.output / "InputDescriptors.json").exists())

    def test_test_failure_publishes_training_and_retry_reuses_completed_molecules(self):
        test_stage = self.root / 'test-stage'
        test_stage.mkdir()
        test_job = replace(self.job, stage_dir=test_stage, stage_py=test_stage / 'H.py',
                           stage_chk=test_stage / 'H.chk', stage_out=test_stage / 'H.out')
        # Use the same dataset and molecule names in training and test: their
        # energies must still be collected in separate scopes.
        flags = ['--test-xyz', str(self.xyz), '--test-ref', str(self.ref), '--force']
        cache, calls = {}, []
        fail_test = True
        def execute(job, grid, *args):
            calls.append(job)
            if job == test_job and fail_test:
                return 1, None, 0
            result = self.run_molecule(job, grid, *args)
            cache[job] = result[1]
            return result
        with patch.object(runner, 'discover_user_jobs', side_effect=lambda *a, **k: [self.job] if k.get('require_restart') else [test_job]), \
                patch.object(runner, 'run_user_job', side_effect=execute), \
                patch.object(runner, 'reusable_user_energy', side_effect=lambda job, *a: cache.get(job)):
            self.invoke('input', flags)
            result = json.loads((self.output / 'SinglePointResults.input.json').read_text())
            self.assertTrue(result['complete'])
            self.assertTrue(result['trainingComplete'])
            self.assertFalse(result['testComplete'])
            self.assertFalse(result['evaluationComplete'])
            self.assertEqual(result['testCoverage']['failedMolecules'], ['H'])
            self.assertEqual(result['testCoverage']['completedReactions'], 0)
            self.assertEqual(result['testTargetRows'], [])
            ready = json.loads((self.output / 'InputDescriptors.json').read_text())
            self.assertEqual(result['descriptor_snapshot_id'], ready['id'])
            self.assertTrue(ready['complete'])
            fail_test = False
            calls.clear()
            self.invoke('input', flags)
            self.assertEqual(calls, [test_job])
            result = json.loads((self.output / 'SinglePointResults.input.json').read_text())
            self.assertTrue(result['complete'])
            self.assertTrue(result['testComplete'])
            self.assertTrue(result['evaluationComplete'])
            self.assertEqual(len(result['targetRows']), 1)
            self.assertEqual(len(result['testTargetRows']), 1)
            self.assertIsNotNone(result['descriptor_snapshot_id'])
            calls.clear()
            self.invoke('input', flags)
            self.assertEqual(calls, [])
            result = json.loads((self.output / 'SinglePointResults.input.json').read_text())
            self.assertTrue(result['complete'])
            self.assertEqual(result['wavefunction_overlap']['total'], 2)

    def test_training_failure_still_blocks_descriptors_when_test_succeeds(self):
        test_stage = self.root / 'test-stage'
        test_stage.mkdir()
        test_job = replace(self.job, stage_dir=test_stage, stage_py=test_stage / 'H.py',
                           stage_chk=test_stage / 'H.chk', stage_out=test_stage / 'H.out')
        def execute(job, grid, *args):
            return (1, None, 0) if job == self.job else self.run_molecule(job, grid, *args)
        with patch.object(runner, 'discover_user_jobs', side_effect=lambda *a, **k: [self.job] if k.get('require_restart') else [test_job]), \
                patch.object(runner, 'run_user_job', side_effect=execute), self.assertRaises(SystemExit):
            self.invoke('input', ['--test-xyz', str(self.xyz), '--test-ref', str(self.ref)])
        result = json.loads((self.output / 'SinglePointResults.input.json').read_text())
        self.assertFalse(result['complete'])
        self.assertFalse(result['trainingComplete'])
        self.assertTrue(result['testComplete'])
        self.assertFalse(result['evaluationComplete'])
        self.assertIsNone(result['descriptor_snapshot_id'])
        self.assertFalse((self.output / 'InputDescriptors.json').exists())

    def test_missing_training_reaction_still_blocks_descriptors(self):
        self.ref.write_text('1 H -0.5\n1 Missing -0.1\n')
        with patch.object(runner, 'discover_user_jobs', return_value=[self.job]), \
                patch.object(runner, 'run_user_job', side_effect=self.run_molecule), self.assertRaises(SystemExit):
            self.invoke('input')
        result = json.loads((self.output / 'SinglePointResults.input.json').read_text())
        self.assertFalse(result['trainingComplete'])
        self.assertEqual(result['trainingCoverage']['completedMolecules'], 1)
        self.assertEqual(result['trainingCoverage']['completedReactions'], 1)
        self.assertEqual(result['trainingCoverage']['totalReactions'], 2)
        self.assertFalse((self.output / 'InputDescriptors.json').exists())


if __name__ == "__main__":
    unittest.main()
