import os
import re
import sqlite3
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import jwt as pyjwt
from apiflask import APIBlueprint
from flask import request, g
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

def _init_db():
    _create_private_file(DB_PATH)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT    UNIQUE NOT NULL,
                email       TEXT    UNIQUE NOT NULL,
                password_hash TEXT  NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
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
        "email": user_row["email"],
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
            options={"require": ["exp", "user_id", "username", "email"]},
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


def is_valid_email(value):
    return isinstance(value, str) and len(value) <= 254 and bool(_EMAIL_RE.fullmatch(value))


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

auth_app = APIBlueprint("Auth", __name__, url_prefix="/auth")


@auth_app.post("/register")
@auth_app.doc(summary="Register an account", description="Create a DFThub account and return a Bearer JWT token.")
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not username or not email or not password:
        return {"success": False, "msg": "Username, email and password are required"}, 400
    if not is_valid_email(email):
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
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
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
@auth_app.doc(summary="Sign in", description="Authenticate with email and password and return a Bearer JWT token.")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return {"success": False, "msg": "Email and password are required"}, 400

    db = get_db()
    try:
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            return {"success": False, "msg": "Invalid email or password"}, 401
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
