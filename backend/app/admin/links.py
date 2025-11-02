import sqlite3

from flask import abort, redirect, request

from ..db import ensure_lists_schema, get_db, init_db
from . import admin_bp


@admin_bp.route("/add", methods=["POST"])
def admin_add():
    """Create a new link from form data."""
    keyword = (request.form.get("keyword") or "").strip()
    title = (request.form.get("title") or "").strip() or None
    url = (request.form.get("url") or "").strip()

    if not keyword or not url:
        abort(400, "Keyword and URL required")

    db = get_db()
    init_db()
    ensure_lists_schema(db)
    try:
        db.execute("INSERT INTO links(keyword, url, title) VALUES (?, ?, ?)", (keyword, url, title))
        db.commit()
    except Exception:
        abort(400, f"Keyword '{keyword}' already exists")
    return redirect("/admin")


@admin_bp.route("/delete", methods=["POST"])
def admin_delete():
    """Delete an existing link by keyword."""
    keyword = (request.form.get("keyword") or "").strip()
    if not keyword:
        abort(400, "Keyword required")
    db = get_db()
    db.execute("DELETE FROM links WHERE lower(keyword) = lower(?)", (keyword,))
    db.commit()
    return redirect("/admin")


@admin_bp.route("/update", methods=["POST"])
def admin_update():
    """Update an existing link."""
    original = (request.form.get("original_keyword") or "").strip()
    keyword = (request.form.get("keyword") or "").strip()
    url = (request.form.get("url") or "").strip()
    title = (request.form.get("title") or "").strip() or None

    if not original or not keyword or not url:
        abort(400, "original_keyword, keyword and url are required")

    db = get_db()
    row = db.execute("SELECT id FROM links WHERE lower(keyword)=lower(?)", (original,)).fetchone()
    if not row:
        abort(404, "link not found")

    try:
        db.execute(
            "UPDATE links SET keyword=?, url=?, title=? WHERE id=?",
            (keyword, url, title, row["id"]),
        )
        db.commit()
    except sqlite3.IntegrityError:
        abort(400, f"Keyword '{keyword}' already exists")

    return redirect(f"/admin?q={keyword}")
