import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from pyscf import gto
from pyscf.scf import chkfile

from dfthub.pipeline import run_ame418_srp as runner


class CheckpointLineageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dfthub-checkpoint-chain-")
        self.root = Path(self.temp.name).resolve()
        self.output_root = self.root / "output"
        self.output_root.mkdir()
        self.metadata = {
            "geometry_sha256": "geometry-hash",
            "basis": "sto-3g",
        }

    def tearDown(self):
        self.temp.cleanup()

    def manifest(self, directory, snapshot_id, created_at=1, **extra):
        snapshot = directory / "input_srp" / snapshot_id
        snapshot.mkdir(parents=True)
        payload = {
            "id": snapshot_id,
            "complete": True,
            "created_at": created_at,
            **self.metadata,
            **extra,
        }
        (snapshot / "manifest.json").write_text(json.dumps(payload))
        (snapshot / "H.chk").write_bytes(b"checkpoint")
        return snapshot

    def test_non_fork_uses_weight_zero_initial_density(self):
        initial = self.output_root / "weight_0" / "work"
        initial.mkdir(parents=True)
        (initial / "H.pychk").write_bytes(b"checkpoint")
        source = runner.resolve_input_checkpoint_source(self.output_root / "weight_3", self.metadata)
        self.assertEqual(source.kind, "initial_density")
        self.assertEqual(source.root, initial.resolve())

    def test_fork_prefers_latest_complete_snapshot(self):
        child = self.output_root / "weight_2" / "fork-1"
        child.mkdir(parents=True)
        old = self.manifest(child, "a" * 32, created_at=1)
        latest = self.manifest(child, "b" * 32, created_at=2)
        source = runner.resolve_input_checkpoint_source(child, self.metadata)
        self.assertEqual(source.kind, "previous_input")
        self.assertEqual(source.snapshot_id, "b" * 32)
        self.assertEqual(source.root, latest.resolve())
        self.assertTrue(old.exists())

    def test_fork_falls_back_to_parent_snapshot(self):
        parent = self.output_root / "weight_2"
        parent_snapshot = self.manifest(parent, "a" * 32)
        child = parent / "fork-1"
        child.mkdir()
        (child / "run.json").write_text(json.dumps({
            "parent": "weight_2",
            "descriptor_snapshot_id": "a" * 32,
        }))
        source = runner.resolve_input_checkpoint_source(child, self.metadata)
        self.assertEqual(source.parent_run, "weight_2")
        self.assertEqual(source.root, parent_snapshot.resolve())

    def test_nested_fork_parent_path_is_supported(self):
        parent = self.output_root / "weight_2" / "fork-1"
        parent_snapshot = self.manifest(parent, "a" * 32)
        child = self.output_root / "weight_2" / "fork-1" / "fork-2"
        child.mkdir(parents=True)
        (child / "run.json").write_text(json.dumps({
            "parent": "weight_2/fork-1",
            "descriptor_snapshot_id": "a" * 32,
        }))
        source = runner.resolve_input_checkpoint_source(child, self.metadata)
        self.assertEqual(source.parent_run, "weight_2/fork-1")
        self.assertEqual(source.root, parent_snapshot.resolve())

    def test_missing_checkpoint_is_reported(self):
        with self.assertRaises(FileNotFoundError):
            runner._checkpoint_for_molecule(self.root, "H")

    def test_generated_input_script_reads_initial_checkpoint(self):
        xyz = self.root / "H.xyz"
        xyz.write_text("1\n0 1\nH 0 0 0\n")
        script = runner.generate_user_script(xyz, "sto-3g")
        self.assertIn("DFTHUB_INITIAL_CHKFILE", script)
        self.assertIn("same_mol", script)
        self.assertIn("run_staged_scf", script)
        self.assertIn("dm0=_dm0", script)


class TestCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dfthub-test-checkpoints-')
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / 'output/weight_0/fork-1'
        self.output.mkdir(parents=True)
        self.parent = self.root / 'output/weight_0/input_srp' / ('a' * 32)
        self.parent.mkdir(parents=True)
        self.source = runner.InputCheckpointSource('previous_input', self.parent, 'a' * 32, 'weight_0')
        self.geometry = self.root / 'test-geometry'
        self.geometry.mkdir()
        self.xyz = self.geometry / 'H2.xyz'
        self.xyz.write_text('2\n0 1\nH 0 0 0\nH 0 0 .74\n')
        self.sources = runner.test_checkpoint_sources(self.output, self.source)

    def tearDown(self):
        self.temp.cleanup()

    def checkpoint(self, root, *, bond=.74, basis='sto-3g', charge=0, spin=0, invalid=False):
        root.mkdir(parents=True, exist_ok=True)
        path = root / 'H2.chk'
        mol = gto.M(atom=f'H 0 0 0; H 0 0 {bond}', basis=basis,
                    charge=charge, spin=spin, verbose=0)
        coeff = np.eye(mol.nao_nr())
        if invalid:
            coeff[0, 0] = np.nan
        occ = np.zeros(mol.nao_nr())
        occ[0] = 2
        chkfile.dump_scf(mol, str(path), -1., np.zeros(mol.nao_nr()), coeff, occ)
        return path.resolve()

    def test_parent_test_checkpoint_is_preferred_and_passed_to_worker(self):
        parent = self.checkpoint(self.parent / 'test_srp/Test_inputfile')
        self.checkpoint(self.sources[1].root)
        # A training molecule with the same name must not create ambiguity.
        self.checkpoint(self.parent / 'Training_inputfile')
        jobs = runner.discover_user_jobs(self.geometry, self.root / 'stage', 'Test', 'sto-3g',
                                        optional_restart_sources=self.sources)
        self.assertEqual(jobs[0].initial_chk, parent)
        self.assertEqual(self.sources[0].snapshot_id, 'a' * 32)
        functional = self.root / 'functional.py'
        functional.write_text('# fixture')
        with patch.object(runner.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            runner.run_user_job(jobs[0], 6, str(functional), 1, 'python')
        self.assertEqual(run.call_args.kwargs['env']['DFTHUB_INITIAL_CHKFILE'], str(parent))

    def test_mismatched_parent_uses_matching_initial_test(self):
        initial = self.checkpoint(self.sources[1].root)
        cases = [{'bond': .8}, {'basis': '3-21g'}, {'charge': 1, 'spin': 1},
                 {'spin': 2}, {'invalid': True}]
        for case in cases:
            with self.subTest(case=case):
                self.checkpoint(self.parent / 'test_srp', **case)
                self.assertEqual(runner.matching_test_checkpoint(self.xyz, 'sto-3g', self.sources), initial)

    def test_changed_atom_order_is_not_used_without_density_projection(self):
        initial = self.checkpoint(self.sources[1].root)
        parent = self.checkpoint(self.parent / 'test_srp')
        mol, record = chkfile.load_scf(str(parent))
        reversed_mol = gto.M(atom='H 0 0 .74; H 0 0 0', basis='sto-3g', verbose=0)
        chkfile.dump_scf(reversed_mol, str(parent), record['e_tot'], record['mo_energy'], record['mo_coeff'], record['mo_occ'])
        self.assertEqual(runner.matching_test_checkpoint(self.xyz, 'sto-3g', self.sources), initial)

    def test_missing_or_ambiguous_parent_falls_back_to_initial(self):
        initial = self.checkpoint(self.sources[1].root)
        self.assertEqual(runner.matching_test_checkpoint(self.xyz, 'sto-3g', self.sources), initial)
        self.checkpoint(self.parent / 'test_srp/first')
        self.checkpoint(self.parent / 'test_srp/second')
        self.assertEqual(runner.matching_test_checkpoint(self.xyz, 'sto-3g', self.sources), initial)

    def test_no_matching_checkpoint_keeps_explicit_minao_fallback(self):
        jobs = runner.discover_user_jobs(self.geometry, self.root / 'stage', 'Test', 'sto-3g',
                                        optional_restart_sources=self.sources)
        self.assertIsNone(jobs[0].initial_chk)

    def test_non_fork_uses_initial_test_scope(self):
        source = runner.InputCheckpointSource('initial_density', self.root / 'output/weight_0/work')
        sources = runner.test_checkpoint_sources(self.root / 'output/weight_2', source)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].kind, 'initial_test')
        self.assertEqual(sources[0].root, self.root / 'output/weight_0/test_work')


if __name__ == "__main__":
    unittest.main()
