import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import tarfile
from pathlib import Path
from unittest.mock import patch


TEST_ROOT = Path(tempfile.mkdtemp(prefix="dfthub-api-security-"))
DATA_DIR = TEST_ROOT / "data"
os.environ["DFTHUB_DATA_DIR"] = str(DATA_DIR)
os.environ["JWT_SECRET"] = ""
os.environ["DFTHUB_WORKERS"] = "0"
os.environ["DFTHUB_MAIL_SUPPRESS"] = "1"

from dfthub.api import app as api_module
from dfthub.api.mail import mail


class ApiSecurityTests(unittest.TestCase):
    def setUp(self):
        # Each case owns its pending work; unconsumed submissions must not leak
        # into the next case's worker or activity assertions.
        for name, value in (("_task_queue", api_module._FairQueue()), ("_spe_inflight", set())):
            mock = patch.object(api_module, name, value)
            mock.start()
            self.addCleanup(mock.stop)

    @classmethod
    def setUpClass(cls):
        common = DATA_DIR / "Work" / "common"
        (common / "program").mkdir(parents=True)
        (common / "default_weights.csv").write_text(
            "Database,Weight\nDEFAULT,1\n"
        )
        template = DATA_DIR / "Work" / "template"
        template.mkdir(parents=True)
        (template / "guide.txt").write_text("template")
        sample = template / "dft_DARC" / "upload"
        sample.mkdir(parents=True)
        (sample / "README.md").write_text("DFThub template")
        (sample / "DFThubDemo.ref").write_text("1 h2 -1.0 1\n")
        (sample / "init_weight.csv").write_text("Database,Description,Type,Source,Number,Inverse Weight\nDFThubDemo,Demo,Input,uploaded,1,0.02\n")
        (sample / "h2.xyz").write_text("2\nH2\nH 0 0 -0.37\nH 0 0 0.37\n")
        with tarfile.open(sample / "DFThubDemo.tgz", "w:gz") as archive:
            archive.add(sample / "h2.xyz", arcname="h2.xyz")
        (sample / "h2.xyz").unlink()
        (DATA_DIR / "submit_count.txt").write_text("0")

        cls.client = api_module.appx.test_client()
        cls.alice_token = cls._register("alice", "alice@example.com")
        cls.bob_token = cls._register("bob", "bob@example.com")
        alice_private = DATA_DIR / "Work" / "alice" / "existing"
        alice_private.mkdir(parents=True)
        (alice_private / "private.txt").write_text("alice private")
        bob_private = DATA_DIR / "Work" / "bob" / "existing"
        bob_private.mkdir(parents=True)
        (bob_private / "private.txt").write_text("bob private")
        (DATA_DIR / "Work" / "alice" / "escape").symlink_to(bob_private, target_is_directory=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_ROOT)

    @classmethod
    def _register(cls, username, email):
        response = cls.client.post(
            "/api_dft/register",
            json={"username": username, "email": email, "password": "secret1"},
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        return response.get_json()["token"]

    @staticmethod
    def _auth(token):
        return {"Authorization": f"Bearer {token}"}

    def _upload_new_work(self, work_name):
        return self.client.put(
            "/api_dft/upload",
            headers=self._auth(self.alice_token),
            data={
                "folder_dir": f"Work/alice/{work_name}/upload",
                "files": [
                    (io.BytesIO(b"archive"), "DARC.zip"),
                    (io.BytesIO(b"0.0"), "DARC_ref"),
                    (
                        io.BytesIO(
                            b"Database,Description,Type,Source,Number,Inverse Weight\n"
                            b"DARC,,,uploaded,,0.02\n"
                        ),
                        "init_weight.csv",
                    ),
                ],
            },
            content_type="multipart/form-data",
        )

    def test_only_count_and_template_downloads_are_public(self):
        count_response = self.client.get("/api_dft/download/submit_count.txt")
        self.assertEqual(count_response.status_code, 200)
        count_response.close()
        template_response = self.client.get(
            "/api_dft/download/Work/template"
        )
        self.assertEqual(template_response.status_code, 200)
        archive = tarfile.open(fileobj=io.BytesIO(template_response.data), mode="r:gz")
        names = archive.getnames()
        self.assertTrue(any(name.endswith("DFThubDemo.tgz") for name in names))
        self.assertTrue(any(name.endswith("DFThubDemo.ref") for name in names))
        self.assertTrue(any(name.endswith("init_weight.csv") for name in names))
        self.assertTrue(any(name.endswith("README.md") for name in names))
        self.assertFalse(any("output/weight_" in name for name in names))
        self.assertTrue(all(member.size > 0 for member in archive.getmembers() if member.isfile()))
        archive.close()
        template_response.close()
        self.assertEqual(
            self.client.get(
                "/api_dft/download/Work/alice/existing/private.txt"
            ).status_code,
            401,
        )
        self.assertEqual(self.client.get("/api_dft/download/%00").status_code, 400)

    def test_private_endpoints_require_authentication(self):
        self.assertEqual(
            self.client.post("/api_dft/test", json={"data": {}}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/api_dft/file_list",
                json={
                    "file_dir": "Work/alice",
                    "file_filter": "*",
                    "file_or_folder": "all",
                },
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.put(
                "/api_dft/upload",
                data={"folder_dir": "Work/alice/x/upload"},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/api_dft/submit",
                json={
                    "mode": "new",
                    "work_dir": "Work/alice/x/",
                    "weightFile": "weight_0",
                },
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.delete("/api_dft/delete/Work/alice/existing").status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/api_dft/cancel", json={"work_dir": "Work/alice/existing", "weightFile": "weight_0"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.delete("/api_dft/delete_run/Work/alice/existing/output/weight_0").status_code,
            401,
        )

    def test_cross_user_paths_and_traversal_are_rejected(self):
        headers = self._auth(self.alice_token)
        own_list = self.client.post(
            "/api_dft/file_list",
            headers=headers,
            json={
                "file_dir": "Work/alice",
                "file_filter": "*",
                "file_or_folder": "folder",
            },
        )
        self.assertEqual(own_list.status_code, 200)
        own_download = self.client.get(
            "/api_dft/download/Work/alice/existing/private.txt", headers=headers
        )
        self.assertEqual(own_download.status_code, 200)
        own_download.close()
        self.assertEqual(
            self.client.get(
                "/api_dft/download/Work/alice/existing/%00", headers=headers
            ).status_code,
            400,
        )
        list_response = self.client.post(
            "/api_dft/file_list",
            headers=headers,
            json={
                "file_dir": "Work/bob",
                "file_filter": "*",
                "file_or_folder": "all",
            },
        )
        self.assertEqual(list_response.status_code, 403)
        self.assertEqual(
            self.client.get(
                "/api_dft/download/Work/bob/existing/private.txt", headers=headers
            ).status_code,
            403,
        )
        self.assertIn(
            self.client.post(
                "/api_dft/file_list", headers=headers,
                json={"file_dir": "Work/alice/escape", "file_filter": "*", "file_or_folder": "all"},
            ).status_code,
            (400, 403),
        )
        self.assertIn(
            self.client.get("/api_dft/download/Work/alice/escape/private.txt", headers=headers).status_code,
            (400, 403),
        )
        traversal = self.client.post(
            "/api_dft/file_list",
            headers=headers,
            json={
                "file_dir": "Work/alice/../bob",
                "file_filter": "*",
                "file_or_folder": "all",
            },
        )
        self.assertEqual(traversal.status_code, 400)

        for endpoint, method, payload in [
            ("/api_dft/cancel", "post", {"work_dir": "Work/bob/existing", "weightFile": "weight_0"}),
            ("/api_dft/submit", "post", {"mode": "new", "work_dir": "Work/bob/existing", "weightFile": "weight_0", "basis": "def2-qzvp"}),
        ]:
            response = getattr(self.client, method)(endpoint, headers=headers, json=payload)
            self.assertIn(response.status_code, (400, 403, 404), (endpoint, response.status_code))

        for endpoint, method, payload in [
            ("/api_dft/cancel", "post", {"work_dir": "Work/alice/../bob", "weightFile": "weight_0"}),
            ("/api_dft/submit", "post", {"mode": "new", "work_dir": "Work/alice/../bob", "weightFile": "weight_0", "basis": "def2-qzvp"}),
        ]:
            response = getattr(self.client, method)(endpoint, headers=headers, json=payload)
            self.assertIn(response.status_code, (400, 403), (endpoint, response.status_code))

        self.assertIn(
            self.client.delete("/api_dft/delete_run/Work/bob/existing/output/weight_0", headers=headers).status_code,
            (400, 403, 404),
        )
        self.assertIn(
            self.client.delete("/api_dft/delete_run/Work/alice/../bob/output/weight_0", headers=headers).status_code,
            (400, 403),
        )
        for endpoint, method, payload in [
            ("/api_dft/cancel", "post", {"work_dir": "Work/alice/escape", "weightFile": "weight_0"}),
            ("/api_dft/submit", "post", {"mode": "new", "work_dir": "Work/alice/escape", "weightFile": "weight_0", "basis": "def2-qzvp"}),
        ]:
            response = getattr(self.client, method)(endpoint, headers=headers, json=payload)
            self.assertIn(response.status_code, (400, 403, 404), (endpoint, response.status_code))
        self.assertIn(
            self.client.delete("/api_dft/delete_run/Work/alice/escape/output/weight_0", headers=headers).status_code,
            (400, 403, 404),
        )

    def test_upload_is_owned_and_weight_folder_only_accepts_weight_csv(self):
        cross_user = self.client.put(
            "/api_dft/upload",
            headers=self._auth(self.alice_token),
            data={
                "folder_dir": "Work/bob/new/upload",
                "files": (io.BytesIO(b"x"), "x.txt"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(cross_user.status_code, 403)

        rejected = self.client.put(
            "/api_dft/upload",
            headers=self._auth(self.alice_token),
            data={
                "folder_dir": "Work/alice/existing/output/weight_1",
                "files": (io.BytesIO(b"print('x')"), "payload.py"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(rejected.status_code, 400)
        symlink_target = self.client.put(
            "/api_dft/upload", headers=self._auth(self.alice_token),
            data={"folder_dir": "Work/alice/escape/upload", "files": (io.BytesIO(b"x"), "x.txt")},
            content_type="multipart/form-data",
        )
        self.assertIn(symlink_target.status_code, (400, 403))

    def test_submit_accepts_frontend_trailing_slash_and_queues_argv(self):
        work_name = "work;no-shell"
        self.assertEqual(self._upload_new_work(work_name).status_code, 200)
        with mail.record_messages() as outbox:
            response = self.client.post(
                "/api_dft/submit",
                headers=self._auth(self.alice_token),
                json={
                    "mode": "new",
                    "work_dir": f"Work/alice/{work_name}/",
                    "weightFile": "weight_0;no-shell",
                    "basis": "def2-qzvp",
                    "email": "alternate@example.com",
                    "reMark": "<script>not email content</script>",
                },
            )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["result"], "work submit success")
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0].recipients, ["alternate@example.com"])
        self.assertNotIn("<script>", outbox[0].html)

        job = api_module._task_queue.get()
        self.assertIsInstance(job["cmd"], list)
        self.assertTrue(
            any(
                argument.endswith(
                    f"Work/alice/{work_name}/output/weight_0;no-shell"
                )
                for argument in job["cmd"]
            )
        )
        self.assertEqual(job["email"], "alternate@example.com")

    def test_submit_rejects_cross_user_invalid_email_and_invalid_basis(self):
        headers = self._auth(self.alice_token)
        cross_user = self.client.post(
            "/api_dft/submit",
            headers=headers,
            json={
                "mode": "new",
                "work_dir": "Work/bob/existing",
                "weightFile": "weight_0",
                "basis": "def2-qzvp",
            },
        )
        self.assertEqual(cross_user.status_code, 403)

        invalid_email = self.client.post(
            "/api_dft/submit",
            headers=headers,
            json={
                "mode": "new",
                "work_dir": "Work/alice/existing",
                "weightFile": "weight_0",
                "basis": "def2-qzvp",
                "email": "not-an-email",
            },
        )
        self.assertEqual(invalid_email.status_code, 422)

        invalid_weight = self.client.post(
            "/api_dft/submit",
            headers=headers,
            json={
                "mode": "new",
                "work_dir": "Work/alice/existing",
                "weightFile": "../weight_0",
                "basis": "def2-qzvp",
            },
        )
        self.assertEqual(invalid_weight.status_code, 400)
        self.assertTrue(api_module.valid_path_component("weight_0 "))

        invalid_basis = self.client.post(
            "/api_dft/submit",
            headers=headers,
            json={
                "mode": "new",
                "work_dir": "Work/alice/existing",
                "weightFile": "weight_0",
                "basis": "unknown-basis",
            },
        )
        self.assertEqual(invalid_basis.status_code, 422)

    def test_register_rejects_invalid_email_and_generic_mail_route_is_gone(self):
        invalid = self.client.post(
            "/api_dft/register",
            json={"username": "badmail", "email": "invalid", "password": "secret1"},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(
            self.client.post(
                "/api_dft/email",
                headers=self._auth(self.alice_token),
                json={"toEmail": "victim@example.com", "infoMsg": "arbitrary"},
            ).status_code,
            404,
        )

    def test_completion_notification_escapes_dynamic_content(self):
        job = {
            "email": "alice@example.com",
            "user": "alice",
            "mode": "optim",
            "work_name": "<b>work</b>",
            "weight_name": "<i>weight</i>",
        }
        with api_module.appx.app_context(), mail.record_messages() as outbox:
            api_module._send_completion_email(job, True)
        self.assertEqual(len(outbox), 1)
        self.assertNotIn("<b>work</b>", outbox[0].html)
        self.assertIn("&lt;b&gt;work&lt;/b&gt;", outbox[0].html)

    def test_auth_files_are_created_with_private_permissions(self):
        self.assertEqual(stat.S_IMODE((DATA_DIR / ".jwt_secret").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((DATA_DIR / "auth.db").stat().st_mode), 0o600)

    def test_auth_initialization_repairs_existing_file_permissions(self):
        repair_root = Path(tempfile.mkdtemp(prefix="dfthub-auth-mode-"))
        try:
            repair_data = repair_root / "data"
            repair_data.mkdir()
            secret_file = repair_data / ".jwt_secret"
            database_file = repair_data / "auth.db"
            secret_file.write_text("existing-secret")
            database_file.touch()
            secret_file.chmod(0o666)
            database_file.chmod(0o666)

            environment = os.environ.copy()
            environment.update(
                {
                    "DFTHUB_DATA_DIR": str(repair_data),
                    "JWT_SECRET": "environment-secret-that-is-at-least-32-bytes",
                    "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            subprocess.run(
                [sys.executable, "-c", "import dfthub.api.auth"],
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(stat.S_IMODE(secret_file.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(database_file.stat().st_mode), 0o600)
        finally:
            shutil.rmtree(repair_root)

    def test_auth_initialization_rejects_empty_secret_file(self):
        empty_root = Path(tempfile.mkdtemp(prefix="dfthub-auth-empty-secret-"))
        try:
            empty_data = empty_root / "data"
            empty_data.mkdir()
            (empty_data / ".jwt_secret").touch()

            environment = os.environ.copy()
            environment.update(
                {
                    "DFTHUB_DATA_DIR": str(empty_data),
                    "JWT_SECRET": "",
                    "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            result = subprocess.run(
                [sys.executable, "-c", "import dfthub.api.auth"],
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("JWT secret must not be empty", result.stderr)
        finally:
            shutil.rmtree(empty_root)

    def _spe_fixture(self, name, with_input=True):
        work = DATA_DIR / "Work" / "alice" / name
        output = work / "output/weight_0"
        output.mkdir(parents=True)
        (output / "CF22D_optimized.py").write_text("# test fixture, never executed\n")
        (output / "process.log").write_text("SUCCESS!\n")
        if with_input:
            (work / "input").mkdir()
            (work / "input/Demo.tgz").write_bytes(b"test")
            (work / "input/Demo.ref").write_text("1 H -0.5\n")
            (work / "input/basis.txt").write_text("cc-pvtz\n")
        return work, output

    def test_spe_defaults_to_input_and_keeps_optimization_log(self):
        work, output = self._spe_fixture("spe_default")
        response = self.client.post("/api_dft/submit", headers=self._auth(self.alice_token), json={
            "mode": "spe", "work_dir": "Work/alice/spe_default", "weightFile": "weight_0",
        })
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        queued = api_module._task_queue.get()
        self.assertEqual(queued["spe_scope"], "input")
        self.assertEqual(queued["cmd"][queued["cmd"].index("--scope") + 1], "input")
        self.assertEqual(queued["cmd"][queued["cmd"].index("--user-basis") + 1], "cc-pvtz")
        self.assertNotIn("--force", queued["cmd"])
        self.assertNotIn("--fresh", queued["cmd"])
        self.assertEqual(queued["cmd"][queued["cmd"].index("--grid") + 1], "6")
        self.assertEqual((output / "process.log").read_text(), "SUCCESS!\n")
        self.assertTrue((output / "spe_input.status.json").is_file())
        self.assertFalse((output / "spe_ame418.log").exists())

    def test_spe_scopes_are_independent_and_duplicates_rejected(self):
        work, output = self._spe_fixture("spe_both")
        payload = {"mode": "spe", "work_dir": "Work/alice/spe_both", "weightFile": "weight_0", "spe_scope": "input"}
        self.assertEqual(self.client.post("/api_dft/submit", headers=self._auth(self.alice_token), json=payload).status_code, 200)
        self.assertEqual(self.client.post("/api_dft/submit", headers=self._auth(self.alice_token), json=payload).status_code, 409)
        first = api_module._task_queue.get()
        payload["spe_scope"] = "ame418"
        self.assertEqual(self.client.post("/api_dft/submit", headers=self._auth(self.alice_token), json=payload).status_code, 200)
        second = api_module._task_queue.get()
        self.assertNotEqual(first["out_log"], second["out_log"])
        self.assertNotIn("--user-xyz", second["cmd"])
        self.assertNotIn("--user-ref", second["cmd"])
        self.assertNotIn("--grid", second["cmd"])
        self.assertEqual(second["cmd"][second["cmd"].index("--scope") + 1], "ame418")

    def test_spe_input_requires_upload_but_ame418_does_not(self):
        self._spe_fixture("spe_no_input", with_input=False)
        payload = {"mode": "spe", "work_dir": "Work/alice/spe_no_input", "weightFile": "weight_0"}
        self.assertEqual(self.client.post("/api_dft/submit", headers=self._auth(self.alice_token), json=payload).status_code, 400)
        payload["spe_scope"] = "invalid"
        self.assertEqual(self.client.post("/api_dft/submit", headers=self._auth(self.alice_token), json=payload).status_code, 422)
        payload["spe_scope"] = "ame418"
        self.assertEqual(self.client.post("/api_dft/submit", headers=self._auth(self.alice_token), json=payload).status_code, 200)
        api_module._task_queue.get()

    def test_spe_worker_persists_status_and_releases_scope(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import Mock
        for code, state in [(0, "Success"), (1, "Failed")]:
            name = "spe_worker_" + str(code)
            _, output = self._spe_fixture(name)
            payload = {"mode": "spe", "work_dir": "Work/alice/" + name, "weightFile": "weight_0", "spe_scope": "input"}
            self.assertEqual(self.client.post("/api_dft/submit", headers=self._auth(self.alice_token), json=payload).status_code, 200)
            job = api_module._task_queue.get()
            queue = Mock()
            queue.get.side_effect = [job, StopIteration]
            def fake_run(*args, **kwargs):
                self.assertEqual(json.loads((output / "spe_input.status.json").read_text())["status"], "Running")
                return SimpleNamespace(returncode=code)
            with patch.object(api_module, "_task_queue", queue), patch.object(api_module.subprocess, "run", side_effect=fake_run), patch.object(api_module, "_send_completion_email"), patch.object(api_module, "_try_generate_cf22d"), self.assertRaises(StopIteration):
                api_module._task_worker()
            self.assertEqual(json.loads((output / "spe_input.status.json").read_text())["status"], state)
            self.assertNotIn(job["spe_key"], api_module._spe_inflight)

    def _refine_fixture(self, name):
        from dfthub.pipeline.refinement import prepare_input_snapshot, write_json
        work, output = self._spe_fixture(name)
        (output / "INPUT").write_text("H " + " ".join(["0"] * 62) + "\n")
        (output / "NEW-params.txt").write_text("\n".join(["1"] * 59))
        (output / "weight.csv").write_text("unchanged weights\n")
        (output / "INPUT_ref").write_text((work / "input/Demo.ref").read_text())
        frozen = output / "optimizer_snapshot/Database_updated/fit"
        frozen.mkdir(parents=True)
        (frozen / "BUILTIN").write_text("unchanged built-in descriptors")
        snapshot = self._ready_snapshot(output, work / "input")
        return work, output, snapshot

    def _ready_snapshot(self, output, inputs):
        from dfthub.pipeline.refinement import prepare_input_snapshot, write_json, file_hash
        snapshot, metadata = prepare_input_snapshot(output, inputs / "Demo.tgz", api_module._find_user_ref(inputs), output / "CF22D_optimized.py", "cc-pvtz", 6)
        (snapshot / "INPUT").write_text("H " + " ".join(["1"] * 60 + ["0", "0"]) + "\n")
        metadata.update(complete=True, descriptor_sha256=file_hash(snapshot / "INPUT"))
        write_json(snapshot / "manifest.json", metadata)
        write_json(output / "InputDescriptors.json", metadata)
        write_json(output / "SinglePointResults.input.json", {"complete": True, "descriptor_snapshot_id": snapshot.name, "scope": "input"})
        write_json(output / "spe_input.status.json", {"status": "Success"})
        return snapshot

    def _refine(self, work, snapshot, fork=None):
        return self.client.post("/api_dft/submit", headers=self._auth(self.alice_token), json={
            "mode": "refine", "work_dir": f"Work/alice/{work.name}", "weightFile": "weight_0",
            "descriptor_snapshot_id": snapshot.name, **({"fork": fork} if fork else {}),
        })

    def test_refine_two_rounds_preserve_sources_and_use_parent_parameters(self):
        work, parent, snapshot = self._refine_fixture("refine_chain")
        original = {p.name: p.read_bytes() for p in parent.iterdir() if p.is_file()}
        response = self._refine(work, snapshot)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["run_id"], "weight_0/fork-1")
        queued = api_module._task_queue.get()
        child = parent / "fork-1"
        for filename in ("weight.csv", "INPUT_ref"):
            self.assertEqual((child / filename).read_bytes(), original[filename])
        self.assertEqual((child / "initial-params.txt").read_bytes(), original["NEW-params.txt"])
        self.assertEqual((child / "INPUT").read_bytes(), (snapshot / "INPUT").read_bytes())
        self.assertIn(str(child / "initial-params.txt"), queued["cmd"])
        self.assertFalse((child / "SinglePointResults.input.json").exists())
        duplicate = self._refine(work, snapshot).get_json()
        self.assertTrue(duplicate["existing"])
        self.assertEqual(duplicate["run_id"], "weight_0/fork-1")
        self.assertEqual(api_module._task_queue.qsize(), 0)
        for name, content in original.items():
            self.assertEqual((parent / name).read_bytes(), content)
        (child / "NEW-params.txt").write_text("\n".join(["2"] * 59))
        (child / "CF22D_optimized.py").write_text("# next functional")
        (child / "process.log").write_text("SUCCESS!\n")
        next_snapshot = self._ready_snapshot(child, child / "input")
        response = self._refine(work, next_snapshot, "fork-1")
        self.assertEqual(response.status_code, 200, response.get_json())
        api_module._task_queue.get()
        grandchild = parent / "fork-2"
        self.assertEqual(json.loads((grandchild / "run.json").read_text())["parent"], "weight_0/fork-1")
        self.assertEqual((grandchild / "initial-params.txt").read_bytes(), (child / "NEW-params.txt").read_bytes())
        self.assertEqual((grandchild / "optimizer_snapshot/Database_updated/fit/BUILTIN").read_bytes(), (parent / "optimizer_snapshot/Database_updated/fit/BUILTIN").read_bytes())

    def test_refine_inherits_test_inputs_across_legacy_snapshots(self):
        work, parent, snapshot = self._refine_fixture("refine_with_test")
        bundle = work / "input/test_set"
        bundle.mkdir()
        manifest = {"geometry": "Test.tgz", "reference": "Test.ref", "dataset": "Test"}
        (bundle / "manifest.json").write_text(json.dumps(manifest))
        (bundle / "Test.tgz").write_bytes(b"test geometry")
        (bundle / "Test.ref").write_text("1 H -0.5\n")
        (parent / "TEST_INPUT").write_text("H " + " ".join(["0"] * 62) + "\n")
        (parent / "TEST_INPUT_ref").write_bytes((bundle / "Test.ref").read_bytes())
        (parent / "TestDescriptors.json").write_text(json.dumps({"basis": "cc-pvtz", "dataset": "Test", "count": 1}))
        # The legacy ready snapshot has no test_set directory at all.
        response = self._refine(work, snapshot)
        self.assertEqual(response.status_code, 200, response.get_json())
        api_module._task_queue.get()
        child = parent / "fork-1"
        self.assertEqual(json.loads((child / "input/test_set/manifest.json").read_text()), manifest)
        for name in ("TEST_INPUT", "TEST_INPUT_ref", "TestDescriptors.json"):
            self.assertEqual((child / name).read_bytes(), (parent / name).read_bytes())
        self.assertFalse((child / "TestMue").exists())
        (child / "NEW-params.txt").write_text("\n".join(["2"] * 59))
        (child / "CF22D_optimized.py").write_text("# child functional")
        next_snapshot = self._ready_snapshot(child, child / "input")
        response = self._refine(work, next_snapshot, "fork-1")
        self.assertEqual(response.status_code, 200, response.get_json())
        api_module._task_queue.get()
        grandchild = parent / "fork-2"
        self.assertEqual(json.loads((grandchild / "input/test_set/manifest.json").read_text()), manifest)
        self.assertEqual((grandchild / "TEST_INPUT").read_bytes(), (parent / "TEST_INPUT").read_bytes())

    def test_refine_allows_incomplete_test_with_verified_training(self):
        work, parent, snapshot = self._refine_fixture("refine_partial_test")
        result_file = parent / "SinglePointResults.input.json"
        result = json.loads(result_file.read_text())
        result.update(trainingComplete=True, testComplete=False, evaluationComplete=False)
        result_file.write_text(json.dumps(result))
        self.assertEqual(self._refine(work, snapshot).status_code, 200)
        self.assertEqual((parent / "fork-1/INPUT").read_bytes(), (snapshot / "INPUT").read_bytes())

    def test_refine_rejects_explicit_incomplete_training(self):
        work, parent, snapshot = self._refine_fixture("refine_partial_train")
        result_file = parent / "SinglePointResults.input.json"
        result = json.loads(result_file.read_text())
        result.update(trainingComplete=False, testComplete=True, evaluationComplete=False)
        result_file.write_text(json.dumps(result))
        self.assertEqual(self._refine(work, snapshot).status_code, 409)
        self.assertFalse((parent / "fork-1").exists())

    def test_refine_rejects_busy_failed_stale_and_old_grid_snapshots(self):
        work, parent, snapshot = self._refine_fixture("refine_invalid")
        status_file = parent / "spe_input.status.json"
        for state in ("Queued", "Running", "Failed"):
            status_file.write_text(json.dumps({"status": state}))
            self.assertEqual(self._refine(work, snapshot).status_code, 409)
        status_file.write_text(json.dumps({"status": "Success"}))
        manifest = snapshot / "manifest.json"
        metadata = json.loads(manifest.read_text())
        manifest.write_text(json.dumps({**metadata, "grid_level": 5}))
        self.assertEqual(self._refine(work, snapshot).status_code, 409)
        manifest.write_text(json.dumps(metadata))
        (parent / "NEW-params.txt").write_text("changed parameters")
        self.assertEqual(self._refine(work, snapshot).status_code, 409)
        self.assertFalse((parent / "fork-1").exists())

    def test_fork_validation_and_input_use_frozen_inputs(self):
        work, parent, snapshot = self._refine_fixture("refine_paths")
        self.assertEqual(self._refine(work, snapshot, "../weight_1").status_code, 400)
        self.assertEqual(self._refine(work, snapshot).status_code, 200)
        api_module._task_queue.get()
        child = parent / "fork-1"
        (child / "CF22D_optimized.py").write_text("# optimized")
        payload = {"mode": "spe", "work_dir": f"Work/alice/{work.name}", "weightFile": "weight_0", "fork": "fork-1"}
        response = self.client.post("/api_dft/submit", headers=self._auth(self.alice_token), json=payload)
        self.assertEqual(response.status_code, 200, response.get_json())
        job = api_module._task_queue.get()
        self.assertIn(str(child / "input/Demo.tgz"), job["cmd"])
        self.assertIn(str(child / "input/INPUT_ref"), job["cmd"])
        self.assertEqual(job["info_dir"], f"Work/alice/{work.name}/output/weight_0/fork-1")

    def test_concurrent_refine_is_idempotent(self):
        from concurrent.futures import ThreadPoolExecutor
        work, parent, snapshot = self._refine_fixture("refine_concurrent")
        def submit(_):
            with api_module.appx.test_client() as client:
                return client.post("/api_dft/submit", headers=self._auth(self.alice_token), json={
                    "mode": "refine", "work_dir": f"Work/alice/{work.name}", "weightFile": "weight_0", "descriptor_snapshot_id": snapshot.name,
                }).get_json()
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(pool.map(submit, range(4)))
        self.assertEqual({reply["run_id"] for reply in replies}, {"weight_0/fork-1"})
        self.assertEqual(sum(not reply["existing"] for reply in replies), 1)
        api_module._task_queue.get()

    def test_worker_continues_when_error_log_parent_was_deleted(self):
        class TrackingQueue(api_module._FairQueue):
            def __init__(self):
                super().__init__()
                self.get_count = 0
                self.waiting_for_third_job = threading.Event()

            def get(self):
                self.get_count += 1
                if self.get_count == 3:
                    self.waiting_for_third_job.set()
                return super().get()

        worker_queue = TrackingQueue()
        second_job_ran = threading.Event()

        class SuccessfulResult:
            returncode = 0

        def fake_run(*args, **kwargs):
            second_job_ran.set()
            return SuccessfulResult()

        missing_log = TEST_ROOT / "deleted-work" / "output" / "process.log"
        failed_job = {
            "cmd": ["not-executed"],
            "out_log": str(missing_log),
            "user": "alice",
        }
        followup_job = {
            "cmd": ["fake-command"],
            "out_log": None,
            "user": "alice",
        }

        with (
            patch.object(api_module, "_task_queue", worker_queue),
            patch.object(api_module.subprocess, "run", side_effect=fake_run),
            patch.object(api_module, "_send_completion_email"),
        ):
            worker = threading.Thread(target=api_module._task_worker, daemon=True)
            worker.start()
            worker_queue.put(failed_job)
            worker_queue.put(followup_job)
            self.assertTrue(second_job_ran.wait(2), "worker did not process the next job")
            self.assertTrue(
                worker_queue.waiting_for_third_job.wait(2),
                "worker did not continue after the next job",
            )
            self.assertTrue(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
