# python
import os
from html import escape

# modules
from flask_mail import Mail, Message

from dfthub.paths import env_flag, load_environment

# Settings come from the process environment or the file named by
# DFTHUB_ENV_FILE (see dfthub.paths.load_environment); nothing else is read.
load_environment()

mail = Mail()

DEFAULT_PUBLIC_URL = "http://127.0.0.1:8188"
_SMTP_VARIABLES = ("DFTHUB_MAIL_SERVER", "DFTHUB_MAIL_USERNAME", "DFTHUB_MAIL_PASSWORD")


def mail_settings():
    """Flask-Mail configuration from DFTHUB_MAIL_*.

    Mail stays off unless DFTHUB_MAIL_SUPPRESS is explicitly 0; an unrecognized
    value is an error rather than a silent "on".
    """
    port_text = os.environ.get("DFTHUB_MAIL_PORT", "").strip() or "25"
    try:
        port = int(port_text)
    except ValueError:
        raise ValueError(f"DFTHUB_MAIL_PORT must be a port number (got {port_text!r})") from None
    use_tls = env_flag("DFTHUB_MAIL_USE_TLS", False)
    use_ssl = env_flag("DFTHUB_MAIL_USE_SSL", False)
    if use_tls and use_ssl:
        raise ValueError("Set only one of DFTHUB_MAIL_USE_TLS (STARTTLS, usually port 587) "
                         "and DFTHUB_MAIL_USE_SSL (implicit TLS, usually port 465)")
    return {
        "MAIL_SERVER": os.environ.get("DFTHUB_MAIL_SERVER", "").strip() or "localhost",
        "MAIL_PORT": port,
        "MAIL_USE_TLS": use_tls,
        "MAIL_USE_SSL": use_ssl,
        "MAIL_DEBUG": False,
        "MAIL_USERNAME": os.environ.get("DFTHUB_MAIL_USERNAME", ""),
        "MAIL_PASSWORD": os.environ.get("DFTHUB_MAIL_PASSWORD", ""),
        "MAIL_DEFAULT_SENDER": os.environ.get("DFTHUB_MAIL_SENDER", "").strip() or "DFThub <noreply@localhost>",
        "MAIL_SUPPRESS_SEND": env_flag("DFTHUB_MAIL_SUPPRESS", True),
        "MAIL_ASCII_ATTACHMENTS": False,
    }


def describe_mail(config):
    """Startup lines that say whether task notifications are sent; never shows credentials."""
    if config["MAIL_SUPPRESS_SEND"]:
        if any(os.environ.get(name, "").strip() for name in _SMTP_VARIABLES):
            return ["Mail: off. SMTP settings are present, but DFTHUB_MAIL_SUPPRESS is not 0; "
                    "set DFTHUB_MAIL_SUPPRESS=0 to send task notifications"]
        return ["Mail: off (no e-mail is sent)"]
    security = "SSL" if config["MAIL_USE_SSL"] else "STARTTLS" if config["MAIL_USE_TLS"] else "unencrypted"
    login = "with SMTP login" if config["MAIL_USERNAME"] else "without SMTP login"
    lines = [f"Mail: on via {config['MAIL_SERVER']}:{config['MAIL_PORT']} ({security}, {login}), "
             f"sender {config['MAIL_DEFAULT_SENDER']}"]
    if config["MAIL_USERNAME"] and security == "unencrypted":
        lines.append("Mail warning: the SMTP password is sent unencrypted; "
                     "set DFTHUB_MAIL_USE_TLS=1 or DFTHUB_MAIL_USE_SSL=1")
    if not os.environ.get("DFTHUB_PUBLIC_URL", "").strip():
        lines.append(f"Mail warning: DFTHUB_PUBLIC_URL is not set; links in e-mails point to {DEFAULT_PUBLIC_URL}")
    return lines


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
    result_url = os.environ.get("DFTHUB_PUBLIC_URL", "").strip() or DEFAULT_PUBLIC_URL
    message.html = (
        f"Hi, {escape(username)}:<br/><br/>"
        f"{escape(summary)}<br/>"
        f"Work: {escape(work_name)}<br/>"
        f"Weight: {escape(weight_name)}<br/><br/>"
        f'Sign in to view the task at <a href="{result_url}">{result_url}</a>.<br/>'
        "<hr/>DFThub"
    )
    mail.send(message)
