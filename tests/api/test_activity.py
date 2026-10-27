"""Job status and deletion follow real queued/running work, not stale logs."""
import json
from contextlib import ExitStack
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_ROOT = Path(tempfile.mkdtemp(prefix="dfthub-activity-")).resolve()
os.environ.update(DFTHUB_DATA_DIR=str(TEST_ROOT / "data"), DFTHUB_WORKERS="0",
                  DFTHUB_MAIL_SUPPRESS="1", JWT_SECRET="isolated-activity-test-secret-at-least-32-bytes")
from dfthub.api import app as api
from dfthub.api import file_api


class ActivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = api.appx.test_client()
        response = cls.client.post("/api_dft/register", json={
            "username": "activity", "email": "activity@example.test", "password": "secret1"})
        cls.headers = {"Authorization": "Bearer " + response.get_json()["token"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_ROOT)

    def setUp(self):
        self.job = api.DATA_DIR / "Work/activity" / self._testMethodName
        self.run = self.job / "output/weight_0"
        self.run.mkdir(parents=True)
        self.queue = api._FairQueue()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(api, "_task_queue", self.queue))
        stack.enter_context(patch.object(file_api, "_live_task_activity", return_value={}))

    def enqueue(self, output=None, scope=None, mode="optim"):
        job = {"user": "activity", "output_dir": str(output or self.run), "mode": mode}
        if scope:
            job["spe_scope"] = scope
        self.queue.put(job)
        return job

    def listing(self, folder):
        response = self.client.post("/api_dft/file_list", headers=self.headers, json={
            "file_dir": str(folder.relative_to(api.DATA_DIR)), "file_filter": "*", "file_or_folder": "folder"})
        self.assertEqual(response.status_code, 200)
        return {row["name"]: row for row in response.get_json()["result"]}

    def delete(self):
        return self.client.delete("/api_dft/delete/" + str(self.job.relative_to(api.DATA_DIR)), headers=self.headers)

    def test_orphaned_submission_without_runs_is_interrupted_and_deletable(self):
        self.run.rmdir()
        (self.job / "process.log").write_text("Work Submit Log\nRun Queued (queue size 1)\n")
        row = self.listing(self.job.parent)[self.job.name]
        self.assertEqual(row["status"], "Interrupted")
        self.assertNotIn("activity_state", row)
        sibling = self.job.parent / "keep"
        sibling.mkdir(exist_ok=True)
        self.assertEqual(self.delete().status_code, 200)
        self.assertFalse(self.job.exists())
        self.assertTrue(sibling.exists())

    def test_actual_queue_is_protected_even_without_a_process(self):
        self.enqueue()
        row = self.listing(self.job.parent)[self.job.name]
        self.assertEqual(row["activity_state"], "queued")
        self.assertEqual(row["activity_status"], "Optimization queued")
        self.assertTrue(api._queued_task(self.run))
        self.assertEqual(self.delete().status_code, 409)
        self.queue.get()
        self.queue.task_done()
        self.assertFalse(api._queued_task(self.run))

    def test_scf_does_not_erase_optimization_completion(self):
        (self.run / "process.log").write_text("SUCCESS!\n")
        self.enqueue(scope="input", mode="spe")
        self.queue.get()
        for folder, name in ((self.job.parent, self.job.name), (self.run.parent, self.run.name)):
            row = self.listing(folder)[name]
            self.assertEqual(row["status"], "Success")
            self.assertEqual(row["activity_state"], "running")
            self.assertEqual(row["activity_status"], "SCF Input running")
        self.assertEqual(self.delete().status_code, 409)
        self.queue.task_done()
        self.assertNotIn("activity_state", self.listing(self.job.parent)[self.job.name])

    def test_active_fork_cannot_be_hidden_by_a_newer_completed_log(self):
        fork = self.run / "fork-1"
        fork.mkdir()
        (fork / "process.log").write_text("QUEUED\nOptimizing parameters\n")
        (self.run / "process.log").write_text("SUCCESS!\n")
        self.enqueue(output=fork, mode="refine")
        self.queue.get()
        row = self.listing(self.job.parent)[self.job.name]
        self.assertEqual(row["activity_state"], "running")
        self.assertIn("Optimizing", row["activity_status"])
        # The original fit remains completed; its fork is a separate run.
        self.assertEqual(self.listing(self.run.parent)[self.run.name]["status"], "Success")
        self.assertEqual(self.delete().status_code, 409)

    def test_energy_task_under_run_is_visible_and_protected(self):
        (self.run / "process.log").write_text("SUCCESS!\n")
        output = self.run / "energy_input/task"
        output.mkdir(parents=True)
        self.enqueue(output=output, scope="energy", mode="spe")
        row = self.listing(self.run.parent)[self.run.name]
        self.assertEqual(row["activity_status"], "DFT energy queued")
        self.assertEqual(self.delete().status_code, 409)

    def test_old_scf_status_file_cannot_block_deletion(self):
        (self.run / "process.log").write_text("SUCCESS!\n")
        (self.run / "spe_input.status.json").write_text(json.dumps({"status": "Running"}))
        self.assertNotIn("activity_state", self.listing(self.run.parent)[self.run.name])
        self.assertEqual(self.delete().status_code, 200)

    def test_logs_are_evaluated_independently_and_last_terminal_marker_wins(self):
        (self.run / "process.log").write_text("QUEUED\nSUCCESS!\n[Error] later failure\n")
        other = self.job / "output/weight_1"
        other.mkdir()
        (other / "process.log").write_text("QUEUED\nSUCCESS!\n")
        self.assertEqual(file_api._derive_status(self.job, {}), "Failed")
        (self.run / "process.log").write_text("QUEUED\n[Error] recovered\nSUCCESS!\n")
        self.assertEqual(file_api._derive_status(self.job, {}), "Success")
        (self.run / "process.log").write_text("QUEUED\nOptimizing parameters\n")
        self.assertEqual(file_api._derive_status(self.job, {}), "Interrupted")


class ProcessActivityTests(unittest.TestCase):
    def test_process_arguments_preserve_spaces_and_identify_scf(self):
        with tempfile.TemporaryDirectory(prefix="dfthub live ") as temporary:
            root = Path(temporary).resolve()
            script = root / "program/run_ame418_srp.py"
            script.parent.mkdir()
            script.write_text("import time\ntime.sleep(30)\n")
            output = root / "output with spaces"
            process = subprocess.Popen([sys.executable, str(script), "--output", str(output), "--scope", "input"])
            from dfthub import processes
            expected = patch.object(processes, "PROGRAM_DIR", script.parent.resolve())
            expected.start()
            try:
                deadline = time.monotonic() + 2
                key = (str(output.resolve()), "input")
                while key not in file_api._live_task_activity() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(file_api._live_task_activity()[key]["status"], "Running")
            finally:
                expected.stop()
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
