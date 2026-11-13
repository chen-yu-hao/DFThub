"""Accounts without e-mail, sign-in by username, and job submission with mail off."""
import io
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TEST_ROOT = Path(tempfile.mkdtemp(prefix="dfthub-optional-email-")).resolve()
DATA_DIR = TEST_ROOT / "data"
os.environ["DFTHUB_DATA_DIR"] = str(DATA_DIR)
os.environ["JWT_SECRET"] = ""
os.environ["DFTHUB_WORKERS"] = "0"
os.environ["DFTHUB_MAIL_SUPPRESS"] = "1"

from dfthub.api import app as api_module
from dfthub.api import auth
from dfthub.api.mail import mail


class OptionalEmailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = api_module.appx.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_ROOT)

    def setUp(self):
        mock = patch.object(api_module, "_task_queue", api_module._FairQueue())
        mock.start()
        self.addCleanup(mock.stop)

    def register(self, username, **extra):
        return self.client.post("/api_dft/register", json={"username": username, "password": "secret1", **extra})

    def login(self, **body):
        return self.client.post("/api_dft/login", json={"password": "secret1", **body})

    def test_features_report_mail_status(self):
        self.assertFalse(self.client.get("/api_dft/features").get_json()["mail"])
        with patch.object(api_module, "_mail_enabled", return_value=True):
            self.assertTrue(self.client.get("/api_dft/features").get_json()["mail"])

    def test_register_without_email_and_sign_in_by_username(self):
        for name in ("noaddr1", "noaddr2"):  # several accounts may lack an address
            response = self.register(name)
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            self.assertIsNone(response.get_json()["user"]["email"])
        self.assertEqual(self.register("blank", email="  ").get_json()["user"]["email"], None)

        signed_in = self.login(login="noaddr1")
        self.assertEqual(signed_in.status_code, 200, signed_in.get_data(as_text=True))
        token = signed_in.get_json()["token"]
        me = self.client.get("/api_dft/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.get_json()["user"], {"id": me.get_json()["user"]["id"], "username": "noaddr1", "email": None})

        self.assertEqual(self.login(username="noaddr2").status_code, 200)
        self.assertEqual(self.login(login="NOADDR1").status_code, 401)
        self.assertEqual(self.login(login="noaddr1", password="wrong-password").status_code, 401)
        self.assertEqual(self.client.post("/api_dft/login", json={"password": "secret1"}).status_code, 400)

    def test_email_sign_in_still_works(self):
        self.assertEqual(self.register("withaddr", email="With.Addr@Example.com").status_code, 200)
        self.assertEqual(self.login(email="with.addr@example.com").status_code, 200)
        self.assertEqual(self.login(login="WITH.ADDR@example.com").status_code, 200)
        self.assertEqual(self.register("other", email="with.addr@example.com").status_code, 409)
        self.assertEqual(self.register("badaddr", email="invalid").status_code, 400)

    def upload_work(self, token, username, work_name):
        response = self.client.put(
            "/api_dft/upload",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "folder_dir": f"Work/{username}/{work_name}/upload",
                "files": [
                    (io.BytesIO(b"archive"), "DARC.zip"),
                    (io.BytesIO(b"0.0"), "DARC_ref"),
                    (io.BytesIO(b"Database,Description,Type,Source,Number,Inverse Weight\nDARC,,,uploaded,,0.02\n"), "init_weight.csv"),
                ],
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def submit(self, token, username, work_name, **extra):
        return self.client.post(
            "/api_dft/submit",
            headers={"Authorization": f"Bearer {token}"},
            json={"mode": "new", "work_dir": f"Work/{username}/{work_name}", "weightFile": "weight_0",
                  "basis": "def2-qzvp", **extra},
        )

    def test_mail_off_needs_no_address_and_keeps_none(self):
        token = self.register("quiet").get_json()["token"]
        self.upload_work(token, "quiet", "job_a")
        with mail.record_messages() as outbox:
            response = self.submit(token, "quiet", "job_a", email="someone@example.com")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(outbox, [])
        self.assertIsNone(api_module._task_queue.get()["email"])

    def test_mail_on_without_any_address_is_rejected(self):
        token = self.register("loud").get_json()["token"]
        self.upload_work(token, "loud", "job_b")
        with patch.object(api_module, "_mail_enabled", return_value=True):
            rejected = self.submit(token, "loud", "job_b")
            self.assertEqual(rejected.status_code, 400)
            self.assertIn("notification email", rejected.get_json()["msg"])
            with mail.record_messages() as outbox:
                accepted = self.submit(token, "loud", "job_b", email="loud@example.com")
        self.assertEqual(accepted.status_code, 200, accepted.get_data(as_text=True))
        self.assertEqual([message.recipients for message in outbox], [["loud@example.com"]])

    def test_mail_on_follow_ups_take_the_address_from_the_request(self):
        """An account without e-mail can run every follow-up when the page sends an address."""
        token = self.register("later").get_json()["token"]
        self.upload_work(token, "later", "job_c")
        follow_ups = {
            "optim": {"mode": "optim", "weightFile": "weight_1"},
            "spe input": {"mode": "spe", "spe_scope": "input", "weightFile": "weight_0"},
            "spe overlap": {"mode": "spe", "spe_scope": "overlap", "weightFile": "weight_0"},
            "spe energy": {"mode": "spe", "spe_scope": "energy", "weightFile": "weight_0", "energy_task": "task_1"},
            "refine": {"mode": "refine", "weightFile": "weight_0"},
        }
        headers = {"Authorization": f"Bearer {token}"}
        with patch.object(api_module, "_mail_enabled", return_value=True):
            for name, body in follow_ups.items():
                with self.subTest(name):
                    body = {"work_dir": "Work/later/job_c", **body}
                    missing = self.client.post("/api_dft/submit", headers=headers, json=body)
                    self.assertEqual(missing.status_code, 400)
                    self.assertIn("notification email", missing.get_json()["msg"])
                    given = self.client.post("/api_dft/submit", headers=headers, json={**body, "email": "later@example.com"})
                    self.assertNotIn("notification email", given.get_json().get("msg", ""), given.get_data(as_text=True))
        with patch.object(api_module, "_mail_enabled", return_value=False):
            quiet = self.client.post("/api_dft/submit", headers=headers, json={"work_dir": "Work/later/job_c", **follow_ups["optim"]})
            self.assertNotIn("notification email", quiet.get_json().get("msg", ""))

    def test_jobs_without_address_send_nothing(self):
        job = {"email": None, "user": "quiet", "mode": "optim", "work_name": "w", "weight_name": "weight_0"}
        with api_module.appx.app_context(), mail.record_messages() as outbox:
            api_module._send_completion_email(job, True)
            api_module._send_submission_email(job)
        self.assertEqual(outbox, [])


class MigrationTests(unittest.TestCase):
    def test_existing_database_keeps_accounts_and_allows_missing_email(self):
        directory = Path(tempfile.mkdtemp(prefix="dfthub-auth-migration-"))
        self.addCleanup(shutil.rmtree, directory)
        database = directory / "auth.db"
        old = sqlite3.connect(database)
        old.execute("""
            CREATE TABLE users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT    UNIQUE NOT NULL,
                email       TEXT    UNIQUE NOT NULL,
                password_hash TEXT  NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        old.execute("INSERT INTO users (id, username, email, password_hash, created_at) VALUES (7, 'old', 'old@example.com', 'hash', '2024-01-02 03:04:05')")
        old.commit()
        old.close()

        with patch.object(auth, "DB_PATH", database):
            auth._init_db()
            auth._init_db()  # a second start leaves the migrated table alone
        conn = sqlite3.connect(database)
        try:
            rows = conn.execute("SELECT id, username, email, password_hash, created_at FROM users").fetchall()
            self.assertEqual(rows, [(7, "old", "old@example.com", "hash", "2024-01-02 03:04:05")])
            conn.execute("INSERT INTO users (username, password_hash) VALUES ('new', 'hash')")
            self.assertEqual(conn.execute("SELECT id FROM users WHERE username = 'new'").fetchone(), (8,))
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO users (username, email, password_hash) VALUES ('dup', 'old@example.com', 'hash')")
            self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE name = 'users_new'").fetchall(), [])
        finally:
            conn.close()

    OLD_SCHEMA = """
        CREATE TABLE users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT    UNIQUE NOT NULL,
            email       TEXT    UNIQUE NOT NULL,
            password_hash TEXT  NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """

    def old_database(self, ids, keep):
        """An auth.db from before this change: accounts `ids` created, all but `keep` deleted."""
        directory = Path(tempfile.mkdtemp(prefix="dfthub-auth-sequence-"))
        self.addCleanup(shutil.rmtree, directory)
        database = directory / "auth.db"
        conn = sqlite3.connect(database)
        conn.execute(self.OLD_SCHEMA)
        for user_id in ids:
            conn.execute("INSERT INTO users (id, username, email, password_hash) VALUES (?, ?, ?, 'hash')",
                         (user_id, f"user{user_id}", f"user{user_id}@example.com"))
        conn.execute(f"DELETE FROM users WHERE id NOT IN ({','.join('?' * len(keep))})", keep)
        conn.commit()
        conn.close()
        return database

    def next_id(self, database):
        conn = sqlite3.connect(database)
        try:
            conn.execute("INSERT INTO users (username, password_hash) VALUES ('next', 'hash')")
            return conn.execute("SELECT id FROM users WHERE username = 'next'").fetchone()[0]
        finally:
            conn.close()

    def test_deleted_ids_are_not_reused(self):
        for keep in ([1, 7], []):
            with self.subTest(kept=keep):
                database = self.old_database([1, 7, 8, 100], keep)
                with patch.object(auth, "DB_PATH", database):
                    auth._init_db()
                    auth._init_db()
                conn = sqlite3.connect(database)
                self.assertEqual([row[0] for row in conn.execute("SELECT id FROM users ORDER BY id")], keep)
                conn.close()
                self.assertEqual(self.next_id(database), 101)

    def test_never_used_table_migrates(self):
        database = self.old_database([], [])
        with patch.object(auth, "DB_PATH", database):
            auth._init_db()
        self.assertEqual(self.next_id(database), 1)

    def test_failed_migration_leaves_the_old_table(self):
        database = self.old_database([1, 7, 8, 100], [1, 7])
        real_connect = sqlite3.connect

        class FailingConnection:
            def __init__(self, *args, **kwargs):
                self.conn = real_connect(*args, **kwargs)

            def execute(self, sql, *args):
                if sql.startswith("DROP TABLE users"):
                    raise sqlite3.OperationalError("simulated failure")
                return self.conn.execute(sql, *args)

            def close(self):
                self.conn.close()

        with patch.object(auth, "DB_PATH", database), patch.object(auth.sqlite3, "connect", FailingConnection):
            with self.assertRaisesRegex(sqlite3.OperationalError, "simulated failure"):
                auth._init_db()
        conn = sqlite3.connect(database)
        try:
            self.assertEqual(conn.execute("SELECT id, email FROM users ORDER BY id").fetchall(),
                             [(1, "user1@example.com"), (7, "user7@example.com")])
            self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE name = 'users_new'").fetchall(), [])
            self.assertEqual(conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'users'").fetchone(), (100,))
            columns = {row[1]: row[3] for row in conn.execute("PRAGMA table_info(users)")}
            self.assertEqual(columns["email"], 1)  # still the old NOT NULL schema
        finally:
            conn.close()
        with patch.object(auth, "DB_PATH", database):
            auth._init_db()  # the next start migrates normally
        self.assertEqual(self.next_id(database), 101)


if __name__ == "__main__":
    unittest.main()
