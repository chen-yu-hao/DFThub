# python
import os
from html import escape
from pathlib import Path

# modules
from flask_mail import Mail, Message

# Secrets must be injected by the process supervisor or an explicitly named
# environment file. Never load a .env file from the source tree implicitly.
_ENV_FILE_NAME = os.environ.get("DFTHUB_ENV_FILE", "").strip()
_ENV_FILE = Path(_ENV_FILE_NAME).expanduser() if _ENV_FILE_NAME else None
if _ENV_FILE is not None and _ENV_FILE.is_file():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _s = _line.strip()
        if not _s or _s.startswith("#") or "=" not in _s:
            continue
        _key, _, _val = _s.partition("=")
        _key, _val = _key.strip(), _val.strip().strip('"').strip("'")
        if _key and _val:
            os.environ.setdefault(_key, _val)

mail = Mail()


def send_task_notification(recipient, username, mode, work_name, weight_name, event, success=None):
    mode_label = {
        "new": "Work",
        "optim": "Optimization",
        "refine": "Self-consistent Input refinement",
        "spe": "Single-point energy calculation",
    }[mode]
    if event == "submitted":
        status = "Submitted"
        summary = "Your task has been submitted and added to the processing queue."
    else:
        status = "Completed" if success else "Failed"
        summary = (
            "Your task completed successfully."
            if success
            else "Your task failed. Sign in to review the process log."
        )

    message = Message(
        f"[DFThub] {mode_label} '{work_name}' {status}", recipients=[recipient]
    )
    result_url = os.environ.get("DFTHUB_PUBLIC_URL", "http://127.0.0.1:8188")
    message.html = (
        f"Hi, {escape(username)}:<br/><br/>"
        f"{escape(summary)}<br/>"
        f"Work: {escape(work_name)}<br/>"
        f"Weight: {escape(weight_name)}<br/><br/>"
        f'Sign in to view the task at <a href="{result_url}">{result_url}</a>.<br/>'
        "<hr/>DFThub"
    )
    mail.send(message)

# 然后用appx实现蓝图
class DefaltMailConfig(object):
    MAIL_SERVER = os.environ.get("DFTHUB_MAIL_SERVER", "localhost")
    MAIL_PORT = int(os.environ.get("DFTHUB_MAIL_PORT", "25"))
    MAIL_USE_TLS = os.environ.get("DFTHUB_MAIL_USE_TLS", "0") == "1"
    MAIL_USE_SSL = os.environ.get("DFTHUB_MAIL_USE_SSL", "0") == "1"
    MAIL_DEBUG = False
    MAIL_USERNAME = os.environ.get("DFTHUB_MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("DFTHUB_MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get(
        "DFTHUB_MAIL_SENDER", "DFThub <noreply@localhost>"
    )
    MAIL_SUPPRESS_SEND = os.environ.get("DFTHUB_MAIL_SUPPRESS", "1") == "1"
    MAIL_ASCII_ATTACHMENTS = False
