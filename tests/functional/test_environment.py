"""Environment file loading and mail settings."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dfthub.paths import env_flag, load_environment
from dfthub.api.mail import describe_mail, mail_settings

MAIL_VARIABLES = [name for name in os.environ if name.startswith("DFTHUB_MAIL_")] + ["DFTHUB_PUBLIC_URL", "DFTHUB_ENV_FILE"]


def clean_environment(**values):
    """Patch os.environ without inherited mail settings, then apply values."""
    environment = {key: value for key, value in os.environ.items() if key not in MAIL_VARIABLES}
    environment.update(values)
    return patch.dict(os.environ, environment, clear=True)


class LoadEnvironmentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "dfthub.env"

    def write(self, text, mode=0o600):
        self.path.write_text(text)
        self.path.chmod(mode)

    def test_loads_values_and_keeps_process_environment_first(self):
        self.write("# comment\n\nDFTHUB_TEST_A='quoted'\nDFTHUB_TEST_B=from-file\nDFTHUB_TEST_EMPTY=\n")
        with clean_environment(DFTHUB_ENV_FILE=str(self.path), DFTHUB_TEST_B="from-process"):
            load_environment()
            load_environment()  # repeated calls do not change anything
            self.assertEqual(os.environ["DFTHUB_TEST_A"], "quoted")
            self.assertEqual(os.environ["DFTHUB_TEST_B"], "from-process")
            self.assertNotIn("DFTHUB_TEST_EMPTY", os.environ)

    def test_without_file_nothing_is_loaded(self):
        with clean_environment():
            load_environment()
            self.assertNotIn("DFTHUB_TEST_A", os.environ)

    def test_missing_file_is_named(self):
        with clean_environment(DFTHUB_ENV_FILE=str(self.path)):
            with self.assertRaisesRegex(ValueError, "does not exist"):
                load_environment()

    def test_readable_by_others_is_rejected(self):
        self.write("DFTHUB_TEST_A=1\n", mode=0o644)
        with clean_environment(DFTHUB_ENV_FILE=str(self.path)):
            with self.assertRaisesRegex(ValueError, "chmod 600"):
                load_environment()

    def test_invalid_line_reports_its_number(self):
        self.write("DFTHUB_TEST_A=1\n# fine\nnot a setting\n")
        with clean_environment(DFTHUB_ENV_FILE=str(self.path)):
            with self.assertRaisesRegex(ValueError, r"dfthub\.env:3: expected KEY=value"):
                load_environment()

    def test_env_flag(self):
        for value, expected in (("1", True), ("TRUE", True), ("on", True), ("0", False), ("no", False), ("", None)):
            with clean_environment(DFTHUB_TEST_FLAG=value):
                self.assertEqual(env_flag("DFTHUB_TEST_FLAG", None), expected)
        with clean_environment(DFTHUB_TEST_FLAG="maybe"):
            with self.assertRaisesRegex(ValueError, "DFTHUB_TEST_FLAG must be 1 or 0"):
                env_flag("DFTHUB_TEST_FLAG", False)


class MailSettingsTests(unittest.TestCase):
    def test_off_by_default(self):
        with clean_environment():
            settings = mail_settings()
            self.assertTrue(settings["MAIL_SUPPRESS_SEND"])
            self.assertEqual((settings["MAIL_SERVER"], settings["MAIL_PORT"]), ("localhost", 25))
            self.assertEqual(describe_mail(settings), ["Mail: off (no e-mail is sent)"])

    def test_smtp_settings_without_switch_are_pointed_out(self):
        with clean_environment(DFTHUB_MAIL_SERVER="smtp.example.org"):
            lines = describe_mail(mail_settings())
            self.assertEqual(len(lines), 1)
            self.assertIn("DFTHUB_MAIL_SUPPRESS=0", lines[0])

    def test_on_describes_server_but_not_credentials(self):
        with clean_environment(DFTHUB_MAIL_SUPPRESS="0", DFTHUB_MAIL_SERVER="smtp.example.org",
                               DFTHUB_MAIL_PORT="587", DFTHUB_MAIL_USE_TLS="1",
                               DFTHUB_MAIL_USERNAME="account-name", DFTHUB_MAIL_PASSWORD="s3cret",
                               DFTHUB_PUBLIC_URL="https://dfthub.example.org"):
            settings = mail_settings()
            self.assertFalse(settings["MAIL_SUPPRESS_SEND"])
            lines = describe_mail(settings)
            self.assertEqual(len(lines), 1)
            self.assertIn("Mail: on via smtp.example.org:587 (STARTTLS, with SMTP login)", lines[0])
            self.assertNotIn("s3cret", lines[0])
            self.assertNotIn("account-name", lines[0])

    def test_on_warns_about_plain_password_and_missing_public_url(self):
        with clean_environment(DFTHUB_MAIL_SUPPRESS="no", DFTHUB_MAIL_USERNAME="account-name"):
            text = "\n".join(describe_mail(mail_settings()))
            self.assertIn("password is sent unencrypted", text)
            self.assertIn("DFTHUB_PUBLIC_URL is not set", text)

    def test_invalid_values_fail_clearly(self):
        cases = ({"DFTHUB_MAIL_SUPPRESS": "maybe"}, {"DFTHUB_MAIL_PORT": "smtp"},
                 {"DFTHUB_MAIL_USE_TLS": "1", "DFTHUB_MAIL_USE_SSL": "1"})
        for values in cases:
            with self.subTest(values=values), clean_environment(**values):
                with self.assertRaises(ValueError):
                    mail_settings()


if __name__ == "__main__":
    unittest.main()
