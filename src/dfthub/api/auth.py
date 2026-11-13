import ipaddress
import os
import re
import sqlite3
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import jwt as pyjwt
from apiflask import APIBlueprint
from flask import current_app, request, g
from werkzeug.security import generate_password_hash, check_password_hash

from dfthub.api.config import DATA_DIR

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_PATH = Path(DATA_DIR) / "auth.db"
_PRIVATE_FILE_MODE = 0o600


def _set_private_mode(path):
    path.chmod(_PRIVATE_FILE_MODE)


def _create_private_file(path):
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, _PRIVATE_FILE_MODE)
    except FileExistsError:
        pass
    else:
        os.close(descriptor)
    _set_private_mode(path)


_secret_file = Path(DATA_DIR) / ".jwt_secret"
if _secret_file.exists():
    _set_private_mode(_secret_file)
JWT_SECRET = os.environ.get("JWT_SECRET", "")
if not JWT_SECRET:
    if _secret_file.exists():
        JWT_SECRET = _secret_file.read_text().strip()
    else:
        generated_secret = secrets.token_hex(32)
        try:
            descriptor = os.open(
                _secret_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, _PRIVATE_FILE_MODE
            )
        except FileExistsError:
            JWT_SECRET = _secret_file.read_text().strip()
        else:
            with os.fdopen(descriptor, "w") as secret_file:
                secret_file.write(generated_secret)
            JWT_SECRET = generated_secret
        _set_private_mode(_secret_file)

if not JWT_SECRET:
    raise RuntimeError("JWT secret must not be empty")

JWT_EXPIRY_DAYS = 7

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

_USERS_TABLE = """
    CREATE TABLE IF NOT EXISTS {name} (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        username    TEXT    UNIQUE NOT NULL,
        email       TEXT    UNIQUE,
        password_hash TEXT  NOT NULL,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""


def _email_is_required(conn):
    columns = conn.execute("PRAGMA table_info(users)").fetchall()
    return any(column[1] == "email" and column[3] for column in columns)


def _init_db():
    _create_private_file(DB_PATH)
    conn = sqlite3.connect(str(DB_PATH), isolation_level=None)
    try:
        conn.execute(_USERS_TABLE.format(name="users"))
        if _email_is_required(conn):
            # Accounts created before e-mail became optional: SQLite cannot drop
            # a NOT NULL constraint in place, so copy the rows into a new table.
            conn.execute("BEGIN IMMEDIATE")
            try:
                if _email_is_required(conn):
                    # AUTOINCREMENT never hands out an ID twice. Dropping the
                    # old table also drops its sqlite_sequence entry, so keep
                    # the highest ID ever issued and restore it afterwards.
                    row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'users'").fetchone()
                    issued = row[0] if row else 0
                    conn.execute(_USERS_TABLE.format(name="users_new"))
                    conn.execute(
                        "INSERT INTO users_new (id, username, email, password_hash, created_at) "
                        "SELECT id, username, email, password_hash, created_at FROM users"
                    )
                    conn.execute("DROP TABLE users")
                    conn.execute("ALTER TABLE users_new RENAME TO users")
                    if issued:
                        updated = conn.execute(
                            "UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'users'", (issued,)
                        ).rowcount
                        if not updated:  # nothing copied, so the new table has no entry yet
                            conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('users', ?)", (issued,))
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
    finally:
        conn.close()
        _set_private_mode(DB_PATH)

_init_db()


def get_db():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _make_token(user_row):
    payload = {
        "user_id": user_row["id"],
        "username": user_row["username"],
        "email": user_row["email"] or "",
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRY_DAYS),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _user_dict(row):
    return {"id": row["id"], "username": row["username"], "email": row["email"]}


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def authenticate_request():
    auth_header = request.headers.get("Authorization", "")
    scheme, separator, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token:
        return {"success": False, "msg": "Authentication required"}, 401
    try:
        data = pyjwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            options={"require": ["exp", "user_id", "username"]},
        )
        g.current_user = data
    except pyjwt.ExpiredSignatureError:
        return {"success": False, "msg": "Token expired"}, 401
    except pyjwt.InvalidTokenError:
        return {"success": False, "msg": "Invalid token"}, 401
    return None


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_error = authenticate_request()
        if auth_error:
            return auth_error
        return f(*args, **kwargs)
    return decorated


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"[A-Za-z0-9_-]{2,32}")


def is_valid_email(value):
    return isinstance(value, str) and len(value) <= 254 and bool(_EMAIL_RE.fullmatch(value))


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

auth_app = APIBlueprint("Auth", __name__, url_prefix="/auth")

# ---------------------------------------------------------------------------
# Local single-user mode (dfthub serve --local)
# ---------------------------------------------------------------------------
# The command line enables it, only for a loopback address. The browser then
# asks /local-session for an ordinary Bearer token, so every other endpoint
# keeps its normal token check. This module never reads it from the
# environment, so a stray variable cannot turn sign-in off.
LOCAL_USER_KEY = "DFTHUB_LOCAL_USER"
_FORWARDING_HEADERS = ("Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Real-IP")


def ensure_local_user(username):
    """Return the account used by local mode, creating it without e-mail if needed.

    A new account gets a random password nobody knows; an existing account
    (for example one registered earlier) is used as it is.
    """
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("The local account name must be 2-32 letters, digits, _ or -")
    db = get_db()
    try:
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user is None:
            db.execute(
                "INSERT INTO users (username, email, password_hash) VALUES (?, NULL, ?)",
                (username, generate_password_hash(secrets.token_urlsafe(32))),
            )
            db.commit()
            user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    finally:
        db.close()
    (Path(DATA_DIR) / "Work" / username).mkdir(parents=True, exist_ok=True)
    return _user_dict(user)


def enable_local_mode(app, username):
    user = ensure_local_user(username)
    app.config[LOCAL_USER_KEY] = user["username"]
    return user


def local_mode_user():
    return current_app.config.get(LOCAL_USER_KEY)


def _is_loopback_name(host):
    """True for localhost, 127.x.x.x and [::1], with or without a port."""
    host = (host or "").strip().lower()
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_direct_local_request():
    """Whether this request comes straight from a browser on this computer.

    Rejects requests relayed by a reverse proxy, pages served under another
    host name (DNS rebinding), and pages of another origin: a browser's Origin
    must match this request's scheme, host and port exactly.
    """
    if not _is_loopback_name(request.remote_addr):
        return False
    if any(request.headers.get(name) for name in _FORWARDING_HEADERS):
        return False
    if not _is_loopback_name(request.host):
        return False
    origin = request.headers.get("Origin")
    if origin and origin.strip().lower() != f"{request.scheme}://{request.host}".lower():
        return False
    return True


def _accounts_disabled():
    return {"success": False, "msg": "Sign-in is turned off: this server runs in local single-user mode"}, 403


@auth_app.post("/local-session")
@auth_app.doc(summary="Start a local session", description="Only in local single-user mode (`dfthub serve --local`): return a Bearer JWT token for the local account. Accepted only from a browser on the same computer, not through a proxy.")
def local_session():
    username = local_mode_user()
    if not username:
        return {"success": False, "msg": "Local single-user mode is not enabled"}, 404
    if not is_direct_local_request():
        return {"success": False, "msg": "Local sessions are only available from this computer, e.g. http://127.0.0.1"}, 403
    db = get_db()
    try:
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    finally:
        db.close()
    if user is None:
        return {"success": False, "msg": "The local account no longer exists; restart dfthub serve --local"}, 500
    return {"success": True, "token": _make_token(user), "user": _user_dict(user)}


@auth_app.post("/register")
@auth_app.doc(summary="Register an account", description="Create a DFThub account and return a Bearer JWT token. The e-mail address is optional; it is used for sign-in and job notifications.")
def register():
    if local_mode_user():
        return _accounts_disabled()
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower() or None
    password = data.get("password") or ""

    if not username or not password:
        return {"success": False, "msg": "Username and password are required"}, 400
    if email is not None and not is_valid_email(email):
        return {"success": False, "msg": "Invalid email address"}, 400
    if len(password) < 6:
        return {"success": False, "msg": "Password must be at least 6 characters"}, 400
    if len(username) < 2 or len(username) > 32:
        return {"success": False, "msg": "Username must be 2-32 characters"}, 400

    # Sanitize username for filesystem safety
    safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if not all(c in safe_chars for c in username):
        return {"success": False, "msg": "Username may only contain letters, digits, _ and -"}, 400

    db = get_db()
    try:
        pw_hash = generate_password_hash(password)
        db.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (username, email, pw_hash),
        )
        db.commit()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        # Create user work directory
        work_dir = Path(DATA_DIR) / "Work" / username
        work_dir.mkdir(parents=True, exist_ok=True)
        token = _make_token(user)
        return {"success": True, "token": token, "user": _user_dict(user)}
    except sqlite3.IntegrityError as e:
        err = str(e).lower()
        if "username" in err:
            return {"success": False, "msg": "Username already taken"}, 409
        if "email" in err:
            return {"success": False, "msg": "Email already registered"}, 409
        return {"success": False, "msg": "Registration failed"}, 409
    finally:
        db.close()


@auth_app.post("/login")
@auth_app.doc(summary="Sign in", description="Authenticate with a username or e-mail address (field `login`; `email` and `username` are accepted too) and a password, and return a Bearer JWT token.")
def login():
    if local_mode_user():
        return _accounts_disabled()
    data = request.get_json(silent=True) or {}
    identifier = (data.get("login") or data.get("email") or data.get("username") or "").strip()
    password = data.get("password") or ""

    if not identifier or not password:
        return {"success": False, "msg": "Username or email and password are required"}, 400

    db = get_db()
    try:
        # Usernames cannot contain "@", so the identifier is unambiguous.
        if "@" in identifier:
            user = db.execute("SELECT * FROM users WHERE email = ?", (identifier.lower(),)).fetchone()
        else:
            user = db.execute("SELECT * FROM users WHERE username = ?", (identifier,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            return {"success": False, "msg": "Invalid username, email or password"}, 401
        token = _make_token(user)
        return {"success": True, "token": token, "user": _user_dict(user)}
    finally:
        db.close()


@auth_app.get("/me")
@auth_app.doc(summary="Get the current user", description="Return the authenticated user's account information.", security=[{"bearerAuth": []}])
@login_required
def me():
    db = get_db()
    try:
        user = db.execute(
            "SELECT * FROM users WHERE id = ?", (g.current_user["user_id"],)
        ).fetchone()
        if not user:
            return {"success": False, "msg": "User not found"}, 404
        return {"success": True, "user": _user_dict(user)}
    finally:
        db.close()
