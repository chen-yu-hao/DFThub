"""Local single-user mode: the local account, /local-session and its request checks."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TEST_ROOT = Path(tempfile.mkdtemp(prefix="dfthub-local-mode-")).resolve()
DATA_DIR = TEST_ROOT / "data"
os.environ["DFTHUB_DATA_DIR"] = str(DATA_DIR)
os.environ["JWT_SECRET"] = ""
os.environ["DFTHUB_WORKERS"] = "0"
os.environ["DFTHUB_MAIL_SUPPRESS"] = "1"

from dfthub.api import app as api_module
from dfthub.api import auth


class LocalModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = api_module.appx
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_ROOT)

    def local_mode(self, username="local"):
        """Enable local mode for one test only."""
        state = patch.dict(self.app.config)
        state.start()
        self.addCleanup(state.stop)
        return auth.enable_local_mode(self.app, username)

    def session(self, **kwargs):
        return self.client.post("/api_dft/local-session", **kwargs)

    def test_off_by_default(self):
        self.assertEqual(self.client.get("/api_dft/features").get_json(), {"mail": False, "local": False})
        self.assertEqual(self.session().status_code, 404)

    def test_local_session_signs_in_the_local_account(self):
        user = self.local_mode()
        self.assertEqual((user["username"], user["email"]), ("local", None))
        self.assertTrue((DATA_DIR / "Work" / "local").is_dir())
        self.assertEqual(self.client.get("/api_dft/features").get_json(), {"mail": False, "local": True})

        response = self.session(headers={"Host": "127.0.0.1:8188", "Origin": "http://127.0.0.1:8188"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        token = response.get_json()["token"]
        me = self.client.get("/api_dft/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.get_json()["user"]["username"], "local")
        # Other endpoints still require the token.
        self.assertEqual(self.client.post("/api_dft/file_list", json={"file_dir": "Work/local", "file_or_folder": "folder"}).status_code, 401)

    def test_enabling_again_reuses_the_account(self):
        first = self.local_mode()
        second = auth.enable_local_mode(self.app, "local")
        self.assertEqual(first, second)

    def test_existing_account_keeps_email_and_password(self):
        registered = self.client.post("/api_dft/register", json={"username": "carol", "email": "carol@example.com", "password": "secret1"})
        self.assertEqual(registered.status_code, 200)
        user = self.local_mode("carol")
        self.assertEqual(user["email"], "carol@example.com")
        self.assertEqual(self.session().get_json()["user"]["username"], "carol")
        self.app.config.pop(auth.LOCAL_USER_KEY)
        self.assertEqual(self.client.post("/api_dft/login", json={"login": "carol", "password": "secret1"}).status_code, 200)

    def test_requests_not_made_directly_on_this_computer_are_refused(self):
        self.local_mode()
        refused = {
            "other host name": {"headers": {"Host": "evil.example:8188"}},
            "DNS rebinding with origin": {"headers": {"Host": "evil.example", "Origin": "http://evil.example"}},
            "other origin": {"headers": {"Origin": "http://evil.example"}},
            "opaque origin": {"headers": {"Origin": "null"}},
            "other loopback port": {"headers": {"Host": "127.0.0.1:8188", "Origin": "http://127.0.0.1:9999"}},
            "other scheme": {"headers": {"Host": "127.0.0.1:8188", "Origin": "https://127.0.0.1:8188"}},
            "other loopback name": {"headers": {"Host": "127.0.0.1:8188", "Origin": "http://localhost:8188"}},
            "IPv6 other port": {"headers": {"Host": "[::1]:8188", "Origin": "http://[::1]:9999"}},
            "reverse proxy": {"headers": {"X-Forwarded-For": "203.0.113.9"}},
            "forwarded": {"headers": {"Forwarded": "for=203.0.113.9"}},
            "real ip": {"headers": {"X-Real-IP": "203.0.113.9"}},
            "remote client": {"environ_base": {"REMOTE_ADDR": "192.0.2.10"}},
        }
        for name, kwargs in refused.items():
            with self.subTest(name):
                response = self.session(**kwargs)
                self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
                self.assertNotIn("token", response.get_json())
        for host in ("127.0.0.1:8188", "localhost:8188", "[::1]:8188", "127.0.0.1"):
            with self.subTest(host=host):
                self.assertEqual(self.session(headers={"Host": host}).status_code, 200)
                # The page's own origin: same scheme, host and port.
                self.assertEqual(self.session(headers={"Host": host, "Origin": f"http://{host}"}).status_code, 200)

    def test_accounts_are_disabled(self):
        self.local_mode()
        register = self.client.post("/api_dft/register", json={"username": "dave", "password": "secret1"})
        self.assertEqual(register.status_code, 403)
        self.assertEqual(self.client.post("/api_dft/login", json={"login": "local", "password": "x"}).status_code, 403)

    def test_invalid_account_name(self):
        for name in ("a", "x" * 33, "../evil", "with space"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                auth.ensure_local_user(name)


if __name__ == "__main__":
    unittest.main()
