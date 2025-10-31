import sqlite3

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
