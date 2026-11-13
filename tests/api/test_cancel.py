import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_ROOT = Path(tempfile.mkdtemp(prefix="dfthub-cancel-")).resolve()
os.environ["DFTHUB_DATA_DIR"] = str(TEST_ROOT / "data")
os.environ["JWT_SECRET"] = "cancel-test-secret"
os.environ["DFTHUB_WORKERS"] = "0"
os.environ["DFTHUB_MAIL_SUPPRESS"] = "1"
from dfthub.api import app as api_module


class CancelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common = Path(os.environ["DFTHUB_DATA_DIR"]) / "Work" / "common"
        (common / "program").mkdir(parents=True)
        (common / "default_weights.csv").write_text("Database,Weight\nDEFAULT,1\n")
        (Path(os.environ["DFTHUB_DATA_DIR"]) / "submit_count.txt").write_text("0")
        response = api_module.appx.test_client().post("/api_dft/register", json={"username": "alice", "email": "alice@example.com", "password": "secret1"})
        cls.client = api_module.appx.test_client()
        cls.token = response.get_json()["token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_ROOT, ignore_errors=True)

    def setUp(self):
        queue_patch = patch.object(api_module, "_task_queue", api_module._FairQueue())
        queue_patch.start()
        self.addCleanup(queue_patch.stop)
        self.root = Path(os.environ["DFTHUB_DATA_DIR"]) / "Work" / "alice" / "demo" / "output" / "weight_0"
        if self.root.parent.exists():
            shutil.rmtree(self.root.parent)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "process.log").write_text("QUEUED\nInitial density calculation\n")
        (self.root / "spe_input.log").write_text("QUEUED\n")
        (self.root / "spe_input.status.json").write_text(json.dumps({"scope": "input", "status": "Queued"}))

    def test_cancel_initial_density_marks_only_the_selected_run(self):
        api_module._task_queue.put({"user": "alice", "output_dir": str(self.root)})
        with patch.object(api_module, "_stop_task_processes", return_value=1) as stop:
            response = self.client.post("/api_dft/cancel", headers=self.headers, json={"work_dir": "Work/alice/demo", "weightFile": "weight_0"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue((self.root / ".cancel_requested").is_file())
        stop.assert_called_once_with(self.root.resolve(), None)
        self.assertEqual(api_module._task_queue.qsize(), 0)

    def test_cancel_scf_uses_scope_marker(self):
        api_module._task_queue.put({"user": "alice", "output_dir": str(self.root), "spe_scope": "input"})
        with patch.object(api_module, "_stop_task_processes", return_value=1) as stop:
            response = self.client.post("/api_dft/cancel", headers=self.headers, json={"work_dir": "Work/alice/demo", "weightFile": "weight_0", "spe_scope": "input"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue((self.root / ".cancel_requested.input").is_file())
        self.assertFalse((self.root / ".cancel_requested").is_file())
        self.assertEqual(json.loads((self.root / "spe_input.status.json").read_text())["status"], "Cancelled")
        stop.assert_called_once_with(self.root.resolve(), "input")
        self.assertEqual(api_module._task_queue.qsize(), 0)

    def test_input_retry_queues_resumable_pipeline(self):
        inputs = self.root.parent.parent / 'input'
        inputs.mkdir(exist_ok=True)
        (inputs / 'H2.tgz').write_bytes(b'fixture archive')
        (inputs / 'H2.ref').write_text('1 H2 -1\n')
        (inputs / 'basis.txt').write_text('sto-3g\n')
        (self.root / 'CF22D_optimized.py').write_text('# fixture functional\n')
        response = self.client.post('/api_dft/submit', headers=self.headers,
                                    json={'mode': 'spe', 'spe_scope': 'input',
                                          'work_dir': 'Work/alice/demo', 'weightFile': 'weight_0'})
        self.assertEqual(response.status_code, 200, response.get_json())
        queued = api_module._task_queue.get()
        try:
            self.assertNotIn('--force', queued['cmd'])
            self.assertNotIn('--fresh', queued['cmd'])
            self.assertEqual(queued['spe_scope'], 'input')
        finally:
            api_module._spe_inflight.discard(queued['spe_key'])
            api_module._task_queue.task_done()

    def test_delete_run_cancels_and_removes_only_run_output(self):
        (self.root.parent / "weight_1").mkdir(parents=True)
        api_module._task_queue.put({"user": "alice", "output_dir": str(self.root), "spe_scope": "input"})
        with patch.object(api_module, "_stop_task_processes", return_value=0):
            response = self.client.delete("/api_dft/delete_run/Work/alice/demo/output/weight_0", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.root.exists())
        self.assertTrue((self.root.parent / "weight_1").is_dir())
        self.assertEqual(api_module._task_queue.qsize(), 0)

    def test_retry_clears_only_its_scope_cancel_marker(self):
        api_module._mark_cancelled(self.root, "input")
        api_module._mark_cancelled(self.root, "ame418")
        job = {"user": "alice", "output_dir": str(self.root), "spe_scope": "input"}
        api_module._task_queue.put(job)
        self.assertFalse(api_module._cancel_requested(job))
        self.assertTrue((self.root / ".cancel_requested.ame418").exists())

    def test_parent_run_with_forks_requires_fork_deletion_first(self):
        fork = self.root / "fork-1"
        fork.mkdir()
        response = self.client.delete("/api_dft/delete_run/Work/alice/demo/output/weight_0", headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(self.root.exists())


if __name__ == "__main__":
    unittest.main()
