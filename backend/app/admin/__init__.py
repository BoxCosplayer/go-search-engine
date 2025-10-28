from flask import Blueprint, abort, redirect, render_template, request

from ..db import ensure_lists_schema, get_db, init_db
from ..utils import to_slug

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/")
def admin_home():
    db = get_db()
    ensure_lists_schema(db)
    rows = db.execute(
        """
        SELECT l.id, l.keyword, l.title, l.url,
               IFNULL(GROUP_CONCAT(li.slug, ', '), '') AS lists_csv
        FROM links l
        LEFT JOIN link_lists ll ON ll.link_id = l.id
        LEFT JOIN lists li ON li.id = ll.list_id
        GROUP BY l.id
        ORDER BY l.keyword COLLATE NOCASE
        """
    ).fetchall()

    all_lists = db.execute("SELECT slug, name FROM lists ORDER BY name COLLATE NOCASE").fetchall()
    return render_template("admin/index.html", rows=rows, all_lists=all_lists)


@admin_bp.route("/add", methods=["POST"])
def admin_add():
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
    keyword = (request.form.get("keyword") or "").strip()
    if not keyword:
        abort(400, "Keyword required")
    db = get_db()
    db.execute("DELETE FROM links WHERE lower(keyword) = lower(?)", (keyword,))
    db.commit()
    return redirect("/admin")


@admin_bp.route("/list-add", methods=["POST"])
def admin_list_add():
    db = get_db()
    ensure_lists_schema(db)
    name = (request.form.get("name") or "").strip()
    slug = (request.form.get("slug") or "").strip()
    desc = (request.form.get("description") or "").strip() or None
    if not name and not slug:
        abort(400, "name or slug required")
    if not slug:
        slug = to_slug(name)
    if not name:
        name = slug.replace("-", " ").title()
    try:
        db.execute("INSERT INTO lists(slug, name, description) VALUES (?, ?, ?)", (slug, name, desc))
        db.commit()
    except Exception:
        abort(400, f"List '{slug}' already exists")

    base_url = request.host_url.rstrip("/")
    list_url = f"{base_url}/lists/{slug}"
    title = f"List - {name}"

    try:
        db.execute("INSERT INTO links(keyword, url, title) VALUES (?, ?, ?)", (slug, list_url, title))
        db.commit()
    except Exception:
        pass

    return redirect("/admin")


@admin_bp.route("/set-lists", methods=["POST"])
def admin_set_lists():
    db = get_db()
    ensure_lists_schema(db)
    keyword = (request.form.get("keyword") or "").strip()
    slugs_raw = (request.form.get("slugs") or "").strip()

    link = db.execute("SELECT id FROM links WHERE lower(keyword)=lower(?)", (keyword,)).fetchone()
    if not link:
        abort(404, "link not found")
    link_id = link["id"]

    slugs = [s.strip().lower() for s in slugs_raw.split(",") if s.strip()]
    slugs = sorted(set(slugs))

    for slug in slugs:
        row = db.execute("SELECT id FROM lists WHERE slug=?", (slug,)).fetchone()
        if not row:
            name = slug.replace("-", " ").title()
            db.execute("INSERT INTO lists(slug, name) VALUES (?, ?)", (slug, name))
    db.commit()

    db.execute("DELETE FROM link_lists WHERE link_id=?", (link_id,))
    for slug in slugs:
        list_id = db.execute("SELECT id FROM lists WHERE slug=?", (slug,)).fetchone()["id"]
        db.execute("INSERT OR IGNORE INTO link_lists(link_id, list_id) VALUES (?, ?)", (link_id, list_id))
    db.commit()
    return redirect("/admin")


@admin_bp.route("/list-delete", methods=["POST"])
def admin_list_delete():
    db = get_db()
    slug = (request.form.get("slug") or "").strip()
    if not slug:
        abort(400, "missing slug")
    row = db.execute("SELECT id FROM lists WHERE lower(slug)=lower(?)", (slug,)).fetchone()
    if not row:
        abort(404, "list not found")
    db.execute("DELETE FROM lists WHERE id=?", (row["id"],))
    db.commit()
    return redirect("/lists")
