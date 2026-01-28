from flask import redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from ..db import ensure_admin_users_schema, get_db
from . import admin_bp
from .auth import (
    admin_user_count,
    create_admin_user,
    fetch_admin_user,
    normalize_username,
    validate_password,
    validate_username,
)


def _render_users(message: str = "", error: str = ""):
    db = get_db()
    ensure_admin_users_schema(db)
    users = db.execute(
        """
        SELECT id, username, is_active, created_at
        FROM admin_users
        ORDER BY username COLLATE NOCASE
        """
    ).fetchall()
    return render_template(
        "admin/users.html",
        users=users,
        message=message,
        error=error,
    )


@admin_bp.route("/users")
def admin_users():
    """Render the admin users management page."""
    return _render_users(
        message=(request.args.get("message") or "").strip(),
        error=(request.args.get("error") or "").strip(),
    )


@admin_bp.route("/users/add", methods=["POST"])
def admin_users_add():
    """Add a new admin user."""
    db = get_db()
    ensure_admin_users_schema(db)
    username = normalize_username(request.form.get("username") or "")
    password = request.form.get("password") or ""

    error = validate_username(username) or validate_password(password)
    if error:
        return redirect(url_for("admin.admin_users", error=error))

    if fetch_admin_user(db, username):
        return redirect(url_for("admin.admin_users", error="Username already exists."))

    create_admin_user(db, username, password, active=True)
    return redirect(url_for("admin.admin_users", message="User added."))


@admin_bp.route("/users/password", methods=["POST"])
def admin_users_password():
    """Update an admin user's password."""
    db = get_db()
    ensure_admin_users_schema(db)
    username = normalize_username(request.form.get("username") or "")
    password = request.form.get("password") or ""

    error = validate_username(username) or validate_password(password)
    if error:
        return redirect(url_for("admin.admin_users", error=error))

    user = fetch_admin_user(db, username)
    if not user:
        return redirect(url_for("admin.admin_users", error="User not found."))

    hashed = generate_password_hash(password)
    db.execute(
        "UPDATE admin_users SET password_hash=? WHERE id=?",
        (hashed, user["id"]),
    )
    db.commit()
    return redirect(url_for("admin.admin_users", message="Password updated."))


@admin_bp.route("/users/toggle", methods=["POST"])
def admin_users_toggle():
    """Enable or disable an admin user."""
    db = get_db()
    ensure_admin_users_schema(db)
    username = normalize_username(request.form.get("username") or "")
    is_active_raw = (request.form.get("is_active") or "").strip()
    is_active = is_active_raw == "1"

    error = validate_username(username)
    if error:
        return redirect(url_for("admin.admin_users", error=error))

    user = fetch_admin_user(db, username)
    if not user:
        return redirect(url_for("admin.admin_users", error="User not found."))

    if not is_active and admin_user_count(db, active_only=True) <= 1:
        return redirect(url_for("admin.admin_users", error="At least one active user is required."))

    db.execute(
        "UPDATE admin_users SET is_active=? WHERE id=?",
        (int(is_active), user["id"]),
    )
    db.commit()
    message = "User enabled." if is_active else "User disabled."
    return redirect(url_for("admin.admin_users", message=message))


@admin_bp.route("/users/delete", methods=["POST"])
def admin_users_delete():
    """Delete an admin user."""
    db = get_db()
    ensure_admin_users_schema(db)
    username = normalize_username(request.form.get("username") or "")
    error = validate_username(username)
    if error:
        return redirect(url_for("admin.admin_users", error=error))

    user = fetch_admin_user(db, username)
    if not user:
        return redirect(url_for("admin.admin_users", error="User not found."))

    db.execute("DELETE FROM admin_users WHERE id=?", (user["id"],))
    db.commit()
    return redirect(url_for("admin.admin_users", message="User deleted."))
