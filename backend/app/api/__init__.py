import sqlite3
from contextlib import suppress

from flask import Blueprint, request

from ..db import ensure_lists_schema, get_db, init_db
from ..utils import to_slug

api_bp = Blueprint("api", __name__)


@api_bp.route("/links", methods=["GET", "POST"])
def links():
    """Links endpoint.

    GET:
        Returns a JSON object with all links:
            { "links": [{"keyword","title","url"}, ...] }

    POST (application/json):
        Body fields:
          - keyword (str, required)
          - url (str, required; must start with http:// or https://)
          - title (str, optional)
        Creates a new link, returning {"ok": true} on success or an error JSON
        with HTTP 400 when validation or uniqueness fails.
    """
    db = get_db()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        keyword = (data.get("keyword") or "").strip()
        url = (data.get("url") or "").strip()
        title = (data.get("title") or "").strip() or None
        if not keyword or not url:
            return {"error": "keyword and url are required"}, 400
        if not (url.startswith("http://") or url.startswith("https://")):
            return {"error": "url must start with http:// or https://"}, 400
        init_db()
        ensure_lists_schema(get_db())
        try:
            db.execute("INSERT INTO links(keyword, url, title) VALUES (?, ?, ?)", (keyword, url, title))
            db.commit()
        except Exception:
            return {"error": f"keyword '{keyword}' already exists"}, 400
        return {"ok": True}

    rows = db.execute("SELECT keyword, title, url FROM links ORDER BY keyword COLLATE NOCASE").fetchall()
    return {"links": [dict(r) for r in rows]}


@api_bp.route("/links/<keyword>", methods=["GET"])
def get_link(keyword: str):
    """Return details for a single link (case-insensitive keyword lookup)."""
    db = get_db()
    row = db.execute(
        "SELECT keyword, title, url FROM links WHERE lower(keyword)=lower(?)",
        (keyword,),
    ).fetchone()
    if not row:
        return {"error": "link not found"}, 404
    return {"link": dict(row)}


@api_bp.route("/links/<keyword>", methods=["PUT", "PATCH"])
def update_link(keyword: str):
    """Update an existing link."""
    db = get_db()
    row = db.execute(
        "SELECT id, keyword, title, url FROM links WHERE lower(keyword)=lower(?)",
        (keyword,),
    ).fetchone()
    if not row:
        return {"error": "link not found"}, 404

    data = request.get_json(silent=True) or {}
    new_keyword = (data.get("keyword") or row["keyword"]).strip()
    new_url = (data.get("url") or row["url"]).strip()
    new_title = (data.get("title") or row["title"] or "").strip() or None

    if not new_keyword or not new_url:
        return {"error": "keyword and url are required"}, 400
    if not (new_url.startswith("http://") or new_url.startswith("https://")):
        return {"error": "url must start with http:// or https://"}, 400

    try:
        db.execute(
            "UPDATE links SET keyword=?, url=?, title=? WHERE id=?",
            (new_keyword, new_url, new_title, row["id"]),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return {"error": f"keyword '{new_keyword}' already exists"}, 400

    return {"ok": True, "link": {"keyword": new_keyword, "title": new_title, "url": new_url}}


@api_bp.route("/links/<keyword>", methods=["DELETE"])
def delete_link(keyword: str):
    """Delete a link by keyword (case-insensitive)."""
    db = get_db()
    row = db.execute(
        "SELECT id FROM links WHERE lower(keyword)=lower(?)",
        (keyword,),
    ).fetchone()
    if not row:
        return {"error": "link not found"}, 404
    db.execute("DELETE FROM links WHERE id=?", (row["id"],))
    db.commit()
    return {"ok": True}


@api_bp.route("/lists", methods=["GET", "POST"])
def lists():
    """Lists endpoint.

    GET:
        Returns all lists as JSON:
            { "lists": [{"slug","name","description"}, ...] }

    POST (application/json):
        Body fields:
          - slug (str, optional)
          - name (str, optional)
          - description (str, optional)
        At least one of slug or name is required. Missing slug is generated
        from name. Missing name is derived from slug. Also creates a shortcut
        link (keyword == slug) pointing to /lists/<slug>. Returns {"ok": true}
        on success or an error JSON with HTTP 400 when validation/uniqueness
        fails.
    """
    db = get_db()
    ensure_lists_schema(db)
    if request.method == "POST":
        data = request.get_json(force=True)
        slug = (data.get("slug") or "").strip()
        name = (data.get("name") or "").strip()
        desc = (data.get("description") or "").strip() or None
        if not slug and not name:
            return {"error": "slug or name required"}, 400
        if not slug:
            slug = to_slug(name)
        if not name:
            name = slug.replace("-", " ").title()
        try:
            db.execute("INSERT INTO lists(slug,name,description) VALUES (?,?,?)", (slug, name, desc))
            db.commit()
        except Exception:
            return {"error": "slug exists"}, 400

        # Create a link to the list
        base_url = request.host_url.rstrip("/")
        list_url = f"{base_url}/lists/{slug}"
        title = f"List - {name}"

        try:
            db.execute("INSERT INTO links(keyword, url, title) VALUES (?, ?, ?)", (slug, list_url, title))
            db.commit()
        except Exception:
            pass

        return {"ok": True}

    rows = db.execute("SELECT slug,name,description FROM lists ORDER BY name COLLATE NOCASE").fetchall()
    return {"lists": [dict(r) for r in rows]}


@api_bp.route("/lists/<slug>", methods=["GET", "PUT", "PATCH", "DELETE"])
def list_detail(slug: str):
    """CRUD operations for a single list (case-insensitive slug lookup)."""
    db = get_db()
    ensure_lists_schema(db)
    info = db.execute(
        "SELECT id, slug, name, description FROM lists WHERE lower(slug)=lower(?)",
        (slug,),
    ).fetchone()

    if request.method == "GET":
        if not info:
            return {"error": "list not found"}, 404
        rows = db.execute(
            """
            SELECT l.keyword, l.title, l.url
            FROM links l
            JOIN link_lists ll ON ll.link_id = l.id
            WHERE ll.list_id = ?
            ORDER BY l.keyword COLLATE NOCASE
            """,
            (info["id"],),
        ).fetchall()
        return {
            "list": {
                "slug": info["slug"],
                "name": info["name"],
                "description": info["description"],
            },
            "links": [dict(r) for r in rows],
        }

    if request.method in {"PUT", "PATCH"}:
        if not info:
            return {"error": "list not found"}, 404
        data = request.get_json(silent=True) or {}
        new_slug = (data.get("slug") or info["slug"]).strip()
        new_name = (data.get("name") or info["name"]).strip()
        new_desc = (data.get("description") or info["description"] or "").strip() or None
        if not new_slug:
            return {"error": "slug required"}, 400
        if not new_name:
            new_name = new_slug.replace("-", " ").title()
        try:
            db.execute(
                "UPDATE lists SET slug=?, name=?, description=? WHERE id=?",
                (new_slug, new_name, new_desc, info["id"]),
            )
            db.commit()
        except sqlite3.IntegrityError:
            return {"error": f"slug '{new_slug}' already exists"}, 400

        # Update the auto-created shortcut link if it exists (best effort).
        with suppress(Exception):
            base_url = request.host_url.rstrip("/")
            list_url = f"{base_url}/lists/{new_slug}"
            title = f"List - {new_name}"
            db.execute(
                "UPDATE links SET keyword=?, url=?, title=? WHERE lower(keyword)=lower(?)",
                (new_slug, list_url, title, slug),
            )
            db.commit()

        return {"ok": True, "list": {"slug": new_slug, "name": new_name, "description": new_desc}}

    # DELETE branch
    if not info:
        return {"error": "list not found"}, 404
    db.execute("DELETE FROM lists WHERE id=?", (info["id"],))
    with suppress(Exception):
        db.execute("DELETE FROM links WHERE lower(keyword)=lower(?)", (slug,))
    db.commit()
    return {"ok": True}


@api_bp.route("/lists/<slug>/links", methods=["GET", "POST"])
def list_links(slug: str):
    """List or append links within a list."""
    db = get_db()
    ensure_lists_schema(db)
    info = db.execute(
        "SELECT id FROM lists WHERE lower(slug)=lower(?)",
        (slug,),
    ).fetchone()
    if not info:
        return {"error": "list not found"}, 404

    if request.method == "GET":
        rows = db.execute(
            """
            SELECT l.keyword, l.title, l.url
            FROM links l
            JOIN link_lists ll ON ll.link_id = l.id
            WHERE ll.list_id = ?
            ORDER BY l.keyword COLLATE NOCASE
            """,
            (info["id"],),
        ).fetchall()
        return {"links": [dict(r) for r in rows]}

    data = request.get_json(silent=True) or {}
    keyword = (data.get("keyword") or "").strip()
    if not keyword:
        return {"error": "keyword required"}, 400
    link = db.execute(
        "SELECT id FROM links WHERE lower(keyword)=lower(?)",
        (keyword,),
    ).fetchone()
    if not link:
        return {"error": "link not found"}, 404
    db.execute(
        "INSERT OR IGNORE INTO link_lists(link_id, list_id) VALUES (?, ?)",
        (link["id"], info["id"]),
    )
    db.commit()
    return {"ok": True}


@api_bp.route("/lists/<slug>/links/<keyword>", methods=["DELETE"])
def remove_list_link(slug: str, keyword: str):
    """Remove a link from a list."""
    db = get_db()
    ensure_lists_schema(db)
    info = db.execute(
        "SELECT id FROM lists WHERE lower(slug)=lower(?)",
        (slug,),
    ).fetchone()
    if not info:
        return {"error": "list not found"}, 404
    link = db.execute(
        "SELECT id FROM links WHERE lower(keyword)=lower(?)",
        (keyword,),
    ).fetchone()
    if not link:
        return {"error": "link not found"}, 404
    db.execute(
        "DELETE FROM link_lists WHERE link_id=? AND list_id=?",
        (link["id"], info["id"]),
    )
    db.commit()
    return {"ok": True}
