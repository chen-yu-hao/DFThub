import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from pyscf import dft, gto, lib

from dfthub.pipeline import compute_scheduler as scheduler
from dfthub.pipeline import refinement
from dfthub.pipeline import run_ame418_srp as runner
from dfthub.pipeline import scf_resume as resume


class StagedScfTests(unittest.TestCase):
    """Real PySCF/HDF5 states, with expensive descriptor evaluation isolated."""
    def setUp(self):
        lib.num_threads(1)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.checkpoint = self.root / 'H2.chk'
        self.mol = gto.M(atom='H 0 0 0; H 0 0 0.74', basis='sto-3g', verbose=0)
        self.functional = SimpleNamespace()

    def tearDown(self):
        self.temp.cleanup()

    def mf(self):
        mf = dft.RKS(self.mol)
        mf.xc = 'pbe'
        mf.grids.level = 0
        mf.conv_tol = 1e-8
        return mf

    def descriptors(self, mf, functional, output, stability=None):
        np.save(output, np.ones(62))
        refinement.write_json(Path(output).with_suffix('.json'), {
            'converged': True, 'energy': float(mf.e_tot),
            'reconstructed_energy': float(mf.e_tot), 'grid_level': mf.grids.level,
            'stability': stability,
        })

    def stable(self, mf):
        return (mf.mo_coeff, None, True, None)

    def test_interrupted_stability_resumes_without_repeating_scf(self):
        mf = self.mf()
        with patch.object(mf, 'stability', side_effect=RuntimeError('interrupted')):
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                resume.run_staged_scf(mf, self.functional, self.checkpoint, 'same')
        self.assertEqual(resume.read_progress(self.checkpoint, 'same')['stage'], 'scf')
        self.assertIsNone(resume.completed_energy(self.checkpoint, 'same', 0))
        mf = self.mf()
        with patch.object(mf, 'kernel', side_effect=AssertionError('SCF repeated')), \
                patch.object(refinement, 'save_scf_descriptors', side_effect=self.descriptors):
            value = resume.run_staged_scf(mf, self.functional, self.checkpoint, 'same')
        self.assertEqual(resume.completed_energy(self.checkpoint, 'same', 0), value)

    def test_descriptor_failure_reuses_stable_checkpoint_and_complete_result(self):
        mf = self.mf()
        with patch.object(mf, 'stability', side_effect=lambda **kw: self.stable(mf)), \
                patch.object(refinement, 'save_scf_descriptors', side_effect=RuntimeError('descriptor interrupted')):
            with self.assertRaisesRegex(RuntimeError, 'descriptor interrupted'):
                resume.run_staged_scf(mf, self.functional, self.checkpoint, 'same')
        self.assertEqual(resume.read_progress(self.checkpoint, 'same')['stage'], 'stable')
        self.assertIsNone(resume.completed_energy(self.checkpoint, 'same', 0))
        mf = self.mf()
        with patch.object(mf, 'kernel', side_effect=AssertionError('SCF repeated')), \
                patch.object(mf, 'stability', side_effect=AssertionError('stability repeated')), \
                patch.object(refinement, 'save_scf_descriptors', side_effect=self.descriptors) as save:
            value = resume.run_staged_scf(mf, self.functional, self.checkpoint, 'same')
            self.assertEqual(save.call_count, 1)
            self.assertEqual(resume.run_staged_scf(self.mf(), self.functional, self.checkpoint, 'same'), value)
            self.assertEqual(save.call_count, 1)
        self.assertIsNone(resume.completed_energy(self.checkpoint, 'changed', 0))
        self.checkpoint.with_suffix('.desc.npy').write_bytes(b'broken')
        self.assertIsNone(resume.completed_energy(self.checkpoint, 'same', 0))
        mf = self.mf()
        with patch.object(mf, 'kernel', side_effect=AssertionError('SCF repeated')), \
                patch.object(mf, 'stability', side_effect=AssertionError('stability repeated')), \
                patch.object(refinement, 'save_scf_descriptors', side_effect=self.descriptors):
            self.assertEqual(resume.run_staged_scf(mf, self.functional, self.checkpoint, 'same'), value)

    def test_new_identity_cannot_restore_old_density_as_completed(self):
        mf = self.mf()
        mf.kernel()
        resume.save_stage(mf, self.checkpoint, 'old', 'stable')
        self.assertIsNone(resume.restore_stage(self.mf(), self.checkpoint, 'new'))
        self.checkpoint.with_suffix('.stable.chk').write_bytes(b'corrupted')
        self.assertIsNone(resume.restore_stage(self.mf(), self.checkpoint, 'old'))


class SnapshotReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / 'output/weight_0'
        self.output.mkdir(parents=True)
        for name in ('INPUT', 'INPUT_ref', 'NEW-params.txt', 'weight.csv', 'CF22D_optimized.py'):
            (self.output / name).write_text(name)
        self.geometry = self.root / 'Input.tgz'
        self.geometry.write_bytes(b'geometry')
        self.test = self.root / 'Test.tgz'
        self.test.write_bytes(b'test geometry')
        self.test_ref = self.root / 'Test.ref'
        self.test_ref.write_text('reference')

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self, **kw):
        return refinement.prepare_input_snapshot(self.output, self.geometry, self.output / 'INPUT_ref',
                self.output / 'CF22D_optimized.py', 'sto-3g', 6, **kw)

    def test_matching_retry_reuses_snapshot_but_changed_parameters_do_not(self):
        first, _ = self.snapshot()
        self.assertEqual(self.snapshot()[0], first)
        (self.output / 'NEW-params.txt').write_text('new fit')
        second, _ = self.snapshot()
        self.assertNotEqual(first, second)
        self.assertNotEqual(self.snapshot(force=True)[0], second)

    def test_geometry_and_test_reference_invalidate_reuse(self):
        args = dict(test_geometry=self.test, test_reference=self.test_ref)
        first, _ = self.snapshot(**args)
        self.assertEqual(self.snapshot(**args)[0], first)
        self.test_ref.write_text('changed test reference')
        second, _ = self.snapshot(**args)
        self.assertNotEqual(first, second)
        self.geometry.write_bytes(b'changed geometry')
        self.assertNotEqual(self.snapshot(**args)[0], second)

    def test_corrupt_source_copy_cannot_be_reused(self):
        first, _ = self.snapshot()
        (first / 'CF22D_optimized.py').write_text('corrupt')
        self.assertNotEqual(self.snapshot()[0], first)


class SchedulingTests(unittest.TestCase):
    def test_same_atoms_with_larger_basis_receive_more_resources(self):
        with tempfile.TemporaryDirectory() as temp:
            xyz = Path(temp) / 'Li4.xyz'
            xyz.write_text('4\n0 1\nLi 0 0 0\nLi 0 0 3\nLi 0 3 0\nLi 3 0 0\n')
            small = scheduler.basis_size(xyz, 'sto-3g')
            large = scheduler.basis_size(xyz, 'aug-cc-pvtz')
            self.assertGreater(large, small)
            self.assertGreater(scheduler.threads_for_basis(large), scheduler.threads_for_basis(small))
            small_mem = int(scheduler.molecule_environment(scheduler.threads_for_basis(small))['DFTHUB_MAXMEM'])
            large_mem = int(scheduler.molecule_environment(scheduler.threads_for_basis(large))['DFTHUB_MAXMEM'])
            self.assertGreater(large_mem, small_mem)

    def test_pool_bounds_aggregate_cpu_and_memory(self):
        lock = threading.Lock()
        active = peak = 0
        def run(item, threads):
            nonlocal active, peak
            with lock:
                active += threads
                peak = max(peak, active)
                self.assertLessEqual(active, 24)
                self.assertLessEqual(active * scheduler.MOLECULAR_MEMORY_MB // scheduler.TASK_THREADS,
                                     scheduler.MOLECULAR_MEMORY_MB)
            time.sleep(.01)
            with lock:
                active -= threads
            return threads
        # Simulate a 24-thread machine independently of the CI runner capacity.
        with patch.object(scheduler, 'TASK_THREADS', 24):
            results = list(scheduler.molecular_pool([40, 120, 250] * 4, lambda _: 4,
                                                    run, total=24, nao=lambda item: item))
        self.assertTrue(all(error is None for _, _, error in results))
        self.assertEqual({result for _, result, _ in results}, {4, 8, 16})
        self.assertLessEqual(peak, 24)

    def test_molecular_process_has_no_wall_clock_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            xyz = root / 'H2.xyz'
            xyz.write_text('2\n0 1\nH 0 0 0\nH 0 0 .74\n')
            functional = root / 'functional.py'
            functional.write_text('fixture')
            job = runner.Job(xyz, xyz, 'Input', 'Input', 'H2', root,
                             root / 'H2.py', root / 'H2.chk', root / 'H2.out', 2,
                             nao=2, basis='sto-3g')
            with patch.object(runner.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
                runner.run_user_job(job, 6, str(functional), 4, 'python')
            self.assertNotIn('timeout', run.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
