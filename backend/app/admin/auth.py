from __future__ import annotations

from flask import Response, redirect, request, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .. import utils
from ..db import get_db

ADMIN_AUTH_REALM = "go-admin"


def _unauthorized(message: str) -> Response:
    headers = {"WWW-Authenticate": f'Basic realm="{ADMIN_AUTH_REALM}"'}
    return Response(message, 401, headers)


def _auth_failed_redirect():
    return redirect(url_for("index"))


def _wants_html_prompt() -> bool:
    return request.path.startswith("/admin") and request.method in {"GET", "HEAD"}


def normalize_username(username: str) -> str:
    return (username or "").strip()


def validate_username(username: str) -> str | None:
    cleaned = normalize_username(username)
    if not cleaned:
        return "Username required."
    if any(ch.isspace() for ch in cleaned):
        return "Username must not contain whitespace."
    return None


def validate_password(password: str) -> str | None:
    if not (password or "").strip():
        return "Password required."
    return None


def admin_user_count(db, active_only: bool = False) -> int:
    if active_only:
        row = db.execute("SELECT COUNT(*) AS c FROM admin_users WHERE is_active=1").fetchone()
    else:
        row = db.execute("SELECT COUNT(*) AS c FROM admin_users").fetchone()
    return int(row["c"]) if row else 0


def fetch_admin_user(db, username: str):
    return db.execute(
        "SELECT id, username, password_hash, is_active FROM admin_users WHERE username COLLATE NOCASE = ?",
        (normalize_username(username),),
    ).fetchone()


def create_admin_user(db, username: str, password: str, active: bool = True) -> None:
    hashed = generate_password_hash(password)
    db.execute(
        "INSERT INTO admin_users(username, password_hash, is_active) VALUES (?, ?, ?)",
        (normalize_username(username), hashed, int(active)),
    )
    db.commit()


def verify_admin_credentials(db, username: str, password: str) -> bool:
    row = fetch_admin_user(db, username)
    if not row or not row["is_active"]:
        return False
    return check_password_hash(row["password_hash"], password)


def require_admin_auth():
    if not utils.config.admin_auth_enabled:
        return None

    db = get_db()
    user_count = admin_user_count(db)

    auth = request.authorization
    if not auth or not auth.username or auth.password is None:
        if user_count == 0:
            if request.path.startswith("/admin"):
                return _unauthorized("No admin users exist. Provide credentials to bootstrap.")
            return _auth_failed_redirect()
        if _wants_html_prompt():
            return _unauthorized("Unauthorized.")
        return _auth_failed_redirect()

    username = auth.username
    password = auth.password

    if user_count == 0:
        error = validate_username(username) or validate_password(password)
        if error:
            return _unauthorized(error)
        create_admin_user(db, username, password, active=True)
        return None

    if not verify_admin_credentials(db, username, password):
        if _wants_html_prompt():
            return _unauthorized("Unauthorized.")
        return _auth_failed_redirect()

    return None
