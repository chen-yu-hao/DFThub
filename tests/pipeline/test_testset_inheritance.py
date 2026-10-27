import json
import shutil
import tempfile
import unittest
from pathlib import Path

from dfthub.pipeline.testset_inheritance import inherit_test_set, ensure_fork_test_set, preserve_test_manifest


class TestSetInheritanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name) / 'job'
        self.parent = self.work / 'output/weight_0'
        self.parent.mkdir(parents=True)
        self.bundle = self.work / 'input/test_set'
        self.bundle.mkdir(parents=True)
        self.manifest = {'geometry': 'test_data.tgz', 'reference': 'test_data.ref', 'dataset': 'data'}
        (self.bundle / 'manifest.json').write_text(json.dumps(self.manifest))
        (self.bundle / 'test_data.tgz').write_bytes(b'geometry fixture')
        (self.bundle / 'test_data.ref').write_text('1 H -0.5\n')
        (self.parent / 'TEST_INPUT').write_text('H ' + ' '.join(['0'] * 62) + '\n')
        (self.parent / 'TEST_INPUT_ref').write_bytes((self.bundle / 'test_data.ref').read_bytes())
        (self.parent / 'TestDescriptors.json').write_text(json.dumps({'dataset': 'data', 'basis': 'aug-cc-pvtz', 'count': 1}))
        self.child = self.fork('fork-1', 'weight_0')

    def tearDown(self):
        self.temp.cleanup()

    def fork(self, name, parent):
        child = self.parent / name
        (child / 'input').mkdir(parents=True)
        (child / 'input/basis.txt').write_text('aug-cc-pvtz\n')
        (child / 'run.json').write_text(json.dumps({'parent': parent}))
        for name in ('INPUT', 'INPUT_ref', 'NEW-params.txt', 'Mue', 'SinglePointResults.input.json', 'spe_input.status.json'):
            (child / name).write_text('existing ' + name)
        return child

    def test_fork_gets_inputs_but_no_parent_results(self):
        before = {path: path.read_bytes() for path in self.child.iterdir() if path.is_file()}
        changes = ensure_fork_test_set(self.child)
        self.assertEqual(len(changes), 6)
        for name in ('TEST_INPUT', 'TEST_INPUT_ref', 'TestDescriptors.json'):
            self.assertEqual((self.child / name).read_bytes(), (self.parent / name).read_bytes())
        self.assertEqual(json.loads((self.child / 'input/test_set/manifest.json').read_text()), self.manifest)
        for name in ('TestMue', 'TestMue.json', 'TestOriginalMue'):
            self.assertFalse((self.child / name).exists())
        for path, value in before.items():
            self.assertEqual(path.read_bytes(), value)
        self.assertEqual(ensure_fork_test_set(self.child), [])

    def test_grandchild_recovers_from_ancestor_with_missing_parent_bundle(self):
        grandchild = self.fork('fork-2', 'weight_0/fork-1')
        changes = ensure_fork_test_set(grandchild)
        self.assertEqual(len(changes), 6)
        self.assertEqual((grandchild / 'TEST_INPUT').read_bytes(), (self.parent / 'TEST_INPUT').read_bytes())

    def test_legacy_pair_gets_only_missing_manifest_and_descriptors(self):
        target = self.child / 'input/test_set'
        target.mkdir()
        for name in ('test_data.tgz', 'test_data.ref'):
            shutil.copy2(self.bundle / name, target / name)
        self.assertEqual(len(ensure_fork_test_set(self.child)), 4)

    def test_dry_run_does_not_write(self):
        changes = inherit_test_set(self.parent, self.child, self.work, dry_run=True)
        self.assertEqual(len(changes), 6)
        self.assertFalse((self.child / 'TEST_INPUT').exists())
        self.assertFalse((self.child / 'input/test_set').exists())

    def test_existing_conflict_is_never_overwritten_or_partially_repaired(self):
        (self.child / 'TEST_INPUT').write_text('different descriptors')
        with self.assertRaisesRegex(ValueError, 'left unchanged'):
            ensure_fork_test_set(self.child)
        self.assertEqual((self.child / 'TEST_INPUT').read_text(), 'different descriptors')
        self.assertFalse((self.child / 'input/test_set').exists())

    def test_mismatched_reference_or_basis_is_rejected(self):
        (self.parent / 'TEST_INPUT_ref').write_text('other reference')
        with self.assertRaisesRegex(ValueError, 'reference do not match'):
            ensure_fork_test_set(self.child)
        (self.parent / 'TEST_INPUT_ref').write_bytes((self.bundle / 'test_data.ref').read_bytes())
        (self.child / 'input/basis.txt').write_text('sto-3g')
        with self.assertRaisesRegex(ValueError, 'basis'):
            ensure_fork_test_set(self.child)
        self.assertFalse((self.child / 'TEST_INPUT').exists())

    def test_job_without_test_set_is_unchanged(self):
        shutil.rmtree(self.bundle)
        for name in ('TEST_INPUT', 'TEST_INPUT_ref', 'TestDescriptors.json'):
            (self.parent / name).unlink()
        self.assertEqual(ensure_fork_test_set(self.child), [])

    def test_snapshot_preserves_or_reconstructs_manifest(self):
        target = self.work / 'snapshot/input/test_set'
        preserve_test_manifest(self.bundle / 'test_data.tgz', self.bundle / 'test_data.ref', target)
        self.assertEqual(json.loads((target / 'manifest.json').read_text()), self.manifest)
        (self.bundle / 'manifest.json').unlink()
        other = self.work / 'other/input/test_set'
        preserve_test_manifest(self.bundle / 'test_data.tgz', self.bundle / 'test_data.ref', other)
        self.assertEqual(json.loads((other / 'manifest.json').read_text()), self.manifest)

    def test_parent_cannot_escape_owning_job(self):
        (self.child / 'run.json').write_text(json.dumps({'parent': '../../someone-else'}))
        with self.assertRaises(ValueError):
            ensure_fork_test_set(self.child)

    def test_snapshot_creation_and_resume_keep_test_manifest(self):
        from dfthub.pipeline.refinement import prepare_input_snapshot
        geometry = self.work / 'Train.tgz'
        geometry.write_bytes(b'training geometry')
        for name in ('INPUT', 'INPUT_ref', 'NEW-params.txt', 'weight.csv', 'CF22D_optimized.py'):
            (self.parent / name).write_text('fixture ' + name)
        args = (self.parent, geometry, self.parent / 'INPUT_ref', self.parent / 'CF22D_optimized.py', 'aug-cc-pvtz', 6)
        kwargs = {'test_geometry': self.bundle / 'test_data.tgz', 'test_reference': self.bundle / 'test_data.ref'}
        snapshot, _ = prepare_input_snapshot(*args, **kwargs)
        manifest = snapshot / 'input/test_set/manifest.json'
        self.assertEqual(json.loads(manifest.read_text()), self.manifest)
        manifest.unlink()
        reused, _ = prepare_input_snapshot(*args, **kwargs)
        self.assertEqual(reused, snapshot)
        self.assertEqual(json.loads(manifest.read_text()), self.manifest)


if __name__ == '__main__':
    unittest.main()
