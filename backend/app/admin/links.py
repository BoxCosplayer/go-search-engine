import sqlite3

from flask import redirect, request

from .. import opensearch
from ..db import get_db
from ..search_cache import invalidate_suggestions_cache
from . import admin_bp
from .home import admin_error


@admin_bp.route("/add", methods=["POST"])
def admin_add():
    """Create a new link from form data."""
    keyword = (request.form.get("keyword") or "").strip()
    title = (request.form.get("title") or "").strip() or None
    url = (request.form.get("url") or "").strip()
    search_enabled = 0

    if not keyword or not url:
        return admin_error("Keyword and URL required", 400)
    if any(ch.isspace() for ch in keyword):
        return admin_error("Keyword cannot contain whitespace", 400)

    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO links(keyword, url, title, search_enabled) VALUES (?, ?, ?, ?)",
            (keyword, url, title, search_enabled),
        )
        db.commit()
        opensearch.refresh_link_opensearch(db, cur.lastrowid, url)
        db.commit()
        invalidate_suggestions_cache()
    except Exception:
        return admin_error(f"Keyword '{keyword}' already exists", 400)
    return redirect("/admin")


@admin_bp.route("/delete", methods=["POST"])
def admin_delete():
    """Delete an existing link by keyword."""
    keyword = (request.form.get("keyword") or "").strip()
    if not keyword:
        return admin_error("Keyword required", 400)
    db = get_db()
    db.execute("DELETE FROM links WHERE keyword COLLATE NOCASE = ?", (keyword,))
    db.commit()
    invalidate_suggestions_cache()
    return redirect("/admin")


@admin_bp.route("/update", methods=["POST"])
def admin_update():
    """Update an existing link."""
    original = (request.form.get("original_keyword") or "").strip()
    keyword = (request.form.get("keyword") or "").strip()
    url = (request.form.get("url") or "").strip()
    title = (request.form.get("title") or "").strip() or None
    search_enabled = 0

    if not original or not keyword or not url:
        return admin_error("original_keyword, keyword and url are required", 400)
    if any(ch.isspace() for ch in keyword):
        return admin_error("Keyword cannot contain whitespace", 400)

    db = get_db()
    row = db.execute(
        "SELECT id FROM links WHERE keyword COLLATE NOCASE = ?",
        (original,),
    ).fetchone()
    if not row:
        return admin_error("link not found", 404)

    try:
        db.execute(
            "UPDATE links SET keyword=?, url=?, title=?, search_enabled=? WHERE id=?",
            (keyword, url, title, search_enabled, row["id"]),
        )
        db.commit()
        opensearch.refresh_link_opensearch(db, row["id"], url)
        db.commit()
        invalidate_suggestions_cache()
    except sqlite3.IntegrityError:
        return admin_error(f"Keyword '{keyword}' already exists", 400)

    return redirect(f"/admin?q={keyword}")
