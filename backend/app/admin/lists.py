import sqlite3
from contextlib import suppress

from flask import redirect, request

from ..db import ensure_lists_schema, get_db
from ..utils import to_slug
from . import admin_bp
from .home import admin_error


@admin_bp.route("/list-add", methods=["POST"])
def admin_list_add():
    """Create a new list and a corresponding shortcut link."""
    db = get_db()
    ensure_lists_schema(db)
    name = (request.form.get("name") or "").strip()
    slug = (request.form.get("slug") or "").strip()
    desc = (request.form.get("description") or "").strip() or None
    if not name and not slug:
        return admin_error("name or slug required", 400)
    if not slug:
        slug = to_slug(name)
    if not name:
        name = slug.replace("-", " ").title()
    try:
        db.execute("INSERT INTO lists(slug, name, description) VALUES (?, ?, ?)", (slug, name, desc))
        db.commit()
    except sqlite3.IntegrityError:
        return admin_error(f"List '{slug}' already exists", 400)

    base_url = request.host_url.rstrip("/")
    list_url = f"{base_url}/lists/{slug}"
    title = f"List - {name}"

    db.execute("INSERT OR IGNORE INTO links(keyword, url, title) VALUES (?, ?, ?)", (slug, list_url, title))
    db.commit()

    return redirect("/admin")


@admin_bp.route("/set-lists", methods=["POST"])
def admin_set_lists():
    """Update a link's associated lists (CSV of slugs)."""
    db = get_db()
    ensure_lists_schema(db)
    keyword = (request.form.get("keyword") or "").strip()
    slugs_raw = (request.form.get("slugs") or "").strip()

    link = db.execute("SELECT id FROM links WHERE lower(keyword)=lower(?)", (keyword,)).fetchone()
    if not link:
        return admin_error("link not found", 404)
    link_id = link["id"]

    slugs = [s.strip().lower() for s in slugs_raw.split(",") if s.strip()]
    slugs = sorted(set(slugs))

    new_lists = []
    for slug in slugs:
        row = db.execute("SELECT id FROM lists WHERE slug=?", (slug,)).fetchone()
        if not row:
            name = slug.replace("-", " ").title()
            db.execute("INSERT INTO lists(slug, name) VALUES (?, ?)", (slug, name))
            new_lists.append((slug, name))
    db.commit()

    if new_lists:
        base_url = request.host_url.rstrip("/")
        for slug_value, name in new_lists:
            list_url = f"{base_url}/lists/{slug_value}"
            title = f"List - {name}"
            with suppress(Exception):  # pragma: no cover - defensive; tested via happy path
                db.execute(
                    "INSERT INTO links(keyword, url, title) VALUES (?, ?, ?)", (slug_value, list_url, title)
                )
        db.commit()

    db.execute("DELETE FROM link_lists WHERE link_id=?", (link_id,))
    for slug in slugs:
        list_id = db.execute("SELECT id FROM lists WHERE slug=?", (slug,)).fetchone()["id"]
        db.execute("INSERT OR IGNORE INTO link_lists(link_id, list_id) VALUES (?, ?)", (link_id, list_id))
    db.commit()
    return redirect("/admin")


@admin_bp.route("/list-delete", methods=["POST"])
def admin_list_delete():
    """Delete a list by slug and redirect to the lists index."""
    db = get_db()
    ensure_lists_schema(db)
    slug = (request.form.get("slug") or "").strip()
    if not slug:
        return admin_error("missing slug", 400)
    row = db.execute("SELECT id, slug FROM lists WHERE lower(slug)=lower(?)", (slug,)).fetchone()
    if not row:
        return admin_error("list not found", 404)
    db.execute("DELETE FROM lists WHERE id=?", (row["id"],))
    db.execute("DELETE FROM links WHERE lower(keyword)=lower(?)", (row["slug"],))
    db.commit()
    return redirect("/lists")
