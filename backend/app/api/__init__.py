import csv
import json
import logging
import os
import sqlite3
from contextlib import suppress
from html import escape
from io import StringIO
from time import perf_counter

from flask import Blueprint, Response, abort, g, redirect, request, url_for
from werkzeug.exceptions import BadRequest, HTTPException

from .. import opensearch
from ..admin.auth import require_admin_auth
from ..db import get_db
from ..search_cache import get_cached_suggestions, invalidate_suggestions_cache
from ..utils import is_supported_redirect_url, sanitize_query, to_slug

api_bp = Blueprint("api", __name__)
logger = logging.getLogger(__name__)


@api_bp.before_request
def _api_require_auth():
    auth_result = require_admin_auth()
    if auth_result is not None:
        return auth_result
    return None


@api_bp.before_request
def _api_log_start():
    g._api_log_start = perf_counter()


@api_bp.after_request
def _api_log_end(response):
    start = getattr(g, "_api_log_start", None)
    elapsed_ms = (perf_counter() - start) * 1000 if start else 0.0
    path = request.full_path.rstrip("?")
    remote = request.remote_addr or "unknown"
    logger.info(
        "API %s %s %s %.1fms remote=%s",
        request.method,
        path,
        response.status_code,
        elapsed_ms,
        remote,
    )
    return response


def _get_json_object():
    if not request.is_json:
        raise BadRequest("Expected application/json")
    data = request.get_json(silent=False)
    if not isinstance(data, dict):
        raise BadRequest("JSON object required")
    return data


@api_bp.errorhandler(HTTPException)
def _handle_http_error(err):
    return {"error": err.description or err.name}, err.code


@api_bp.errorhandler(Exception)
def _handle_unexpected_error(err):
    logger.exception("API error", exc_info=err)
    return {"error": "internal server error"}, 500


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _serialize_link(row):
    return {
        "keyword": row["keyword"],
        "title": row["title"],
        "url": row["url"],
        "search_enabled": bool(row["search_enabled"]),
    }


def _quote_fts_term(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _build_fts_query(term: str) -> tuple[str, list[str], list[str]]:
    tokens = [tok for tok in term.split() if tok]
    long_tokens = [tok for tok in tokens if len(tok) >= 3]
    short_tokens = [tok for tok in tokens if len(tok) < 3]
    if not long_tokens:
        return "", short_tokens, tokens
    return " AND ".join(_quote_fts_term(tok) for tok in long_tokens), short_tokens, tokens


def _like_suggestions(db, tokens: list[str]):
    tokens = [tok for tok in tokens if tok][:3]
    if not tokens:
        return []
    if len(tokens) == 1:
        like = f"%{tokens[0]}%"
        rows = db.execute(
            """
            SELECT keyword, title, url
            FROM links
            WHERE (keyword LIKE ? OR (title IS NOT NULL AND title LIKE ?))
            ORDER BY keyword COLLATE NOCASE LIMIT 10
            """,
            (like, like),
        ).fetchall()
    elif len(tokens) == 2:
        like1 = f"%{tokens[0]}%"
        like2 = f"%{tokens[1]}%"
        rows = db.execute(
            """
            SELECT keyword, title, url
            FROM links
            WHERE (keyword LIKE ? OR (title IS NOT NULL AND title LIKE ?))
              AND (keyword LIKE ? OR (title IS NOT NULL AND title LIKE ?))
            ORDER BY keyword COLLATE NOCASE LIMIT 10
            """,
            (like1, like1, like2, like2),
        ).fetchall()
    else:
        like1 = f"%{tokens[0]}%"
        like2 = f"%{tokens[1]}%"
        like3 = f"%{tokens[2]}%"
        rows = db.execute(
            """
            SELECT keyword, title, url
            FROM links
            WHERE (keyword LIKE ? OR (title IS NOT NULL AND title LIKE ?))
              AND (keyword LIKE ? OR (title IS NOT NULL AND title LIKE ?))
              AND (keyword LIKE ? OR (title IS NOT NULL AND title LIKE ?))
            ORDER BY keyword COLLATE NOCASE LIMIT 10
            """,
            (like1, like1, like2, like2, like3, like3),
        ).fetchall()
    return [dict(row) for row in rows]


def _suggestions_cache_key(db, term: str) -> str:
    term_key = (term or "").strip().lower()
    if not term_key:
        return ""
    try:
        row = db.execute("PRAGMA database_list").fetchone()
        db_path = row[2] if row and len(row) > 2 else ""
    except Exception:
        db_path = ""
    try:
        row = db.execute("PRAGMA data_version").fetchone()
        data_version = int(row[0]) if row else 0
    except Exception:
        data_version = 0
    return f"{db_path}|{data_version}|{term_key}"


def _search_suggestions(db, term: str):
    """Return search suggestions for a query term."""
    term = (term or "").strip()
    if not term:
        return []

    def _load():
        fts_query, short_tokens, tokens = _build_fts_query(term)
        if fts_query:
            rows = db.execute(
                """
                SELECT l.keyword, l.title, l.url
                FROM links_fts f
                JOIN links l ON l.id = f.rowid
                WHERE links_fts MATCH ?
                ORDER BY bm25(links_fts), l.keyword COLLATE NOCASE
                LIMIT 50
                """,
                (fts_query,),
            ).fetchall()

            if short_tokens:
                lowered = [tok.lower() for tok in short_tokens]
                filtered = []
                for row in rows:
                    hay = f"{row['keyword']} {row['title'] or ''}".lower()
                    if all(tok in hay for tok in lowered):
                        filtered.append(row)
                rows = filtered

            return [dict(row) for row in rows[:10]]

        return _like_suggestions(db, tokens)

    cache_key = _suggestions_cache_key(db, term)
    return get_cached_suggestions(cache_key, _load)


def _select_links_with_lists(db):
    """Return rows of shortcuts with joined list slugs."""
    return db.execute(
        """
        SELECT l.keyword, l.title, l.url, l.search_enabled,
               IFNULL(GROUP_CONCAT(li.slug, ', '), '') AS lists_csv
        FROM links l
        LEFT JOIN link_lists ll ON ll.link_id = l.id
        LEFT JOIN lists li ON li.id = ll.list_id
        GROUP BY l.id
        ORDER BY l.keyword COLLATE NOCASE
        """
    ).fetchall()


def _delete_link(db, link_id):
    """Remove a link and its list relationships."""
    db.execute("DELETE FROM link_lists WHERE link_id=?", (link_id,))
    db.execute("DELETE FROM links WHERE id=?", (link_id,))


def _import_shortcuts_from_csv(db, file_storage):
    """Parse the provided CSV upload and merge shortcuts into the database."""
    payload = file_storage.read()
    if not payload:
        return 0
    text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else str(payload)
    if not text.strip():
        return 0
    buffer = StringIO(text)
    reader = csv.DictReader(buffer)

    inserted = 0
    updated = 0
    pending_discovery: dict[int, str] = {}
    with db:
        for row in reader:
            keyword = (row.get("keyword") or "").strip()
            url = (row.get("url") or "").strip()
            if not keyword or not url:
                continue
            if not is_supported_redirect_url(url):
                continue
            title = (row.get("title") or "").strip()
            search_enabled = 0

            existing_keyword = db.execute(
                "SELECT id FROM links WHERE keyword COLLATE NOCASE = ?",
                (keyword,),
            ).fetchone()
            existing_url = db.execute(
                "SELECT id FROM links WHERE url COLLATE NOCASE = ?",
                (url,),
            ).fetchone()

            if existing_keyword:
                link_id = existing_keyword["id"]
                db.execute(
                    "UPDATE links SET keyword=?, url=?, title=?, search_enabled=? WHERE id=?",
                    (keyword, url, title or None, search_enabled, link_id),
                )
                updated += 1
            elif existing_url:
                link_id = existing_url["id"]
                db.execute(
                    "UPDATE links SET keyword=?, url=?, title=?, search_enabled=? WHERE id=?",
                    (keyword, url, title or None, search_enabled, link_id),
                )
                updated += 1
            else:
                cur = db.execute(
                    "INSERT INTO links(keyword, url, title, search_enabled) VALUES (?, ?, ?, ?)",
                    (keyword, url, title or None, search_enabled),
                )
                link_id = cur.lastrowid
                inserted += 1
            pending_discovery[link_id] = url

            duplicates = db.execute(
                "SELECT id FROM links WHERE url COLLATE NOCASE = ? AND id <> ?",
                (url, link_id),
            ).fetchall()
            for duplicate in duplicates:
                _delete_link(db, duplicate["id"])

            lists_field = row.get("lists") or ""
            slugs = [slug.strip() for slug in lists_field.split(",") if slug.strip()]
            list_ids: list[int] = []
            for slug in slugs:
                list_row = db.execute(
                    "SELECT id FROM lists WHERE slug COLLATE NOCASE = ?",
                    (slug,),
                ).fetchone()
                if list_row:
                    list_id = list_row["id"]
                else:
                    list_cursor = db.execute(
                        "INSERT INTO lists(slug, name) VALUES (?, ?)",
                        (slug, slug),
                    )
                    list_id = list_cursor.lastrowid
                list_ids.append(list_id)

            db.execute("DELETE FROM link_lists WHERE link_id=?", (link_id,))
            for list_id in list_ids:
                db.execute(
                    "INSERT INTO link_lists(link_id, list_id) VALUES (?, ?)",
                    (link_id, list_id),
                )

    updates: list[tuple[str | None, str | None, int, int]] = []
    for link_id, link_url in pending_discovery.items():
        discovered = opensearch.discover_opensearch_template(link_url)
        if discovered:
            doc_url, template = discovered
            updates.append((doc_url, template, 1, link_id))
        else:
            updates.append((None, None, 0, link_id))

    if updates:
        with db:
            db.executemany(
                """
                UPDATE links
                SET opensearch_doc_url=?, opensearch_template=?, search_enabled=?
                WHERE id=?
                """,
                updates,
            )

    return inserted + updated


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
        data = _get_json_object()
        keyword = (data.get("keyword") or "").strip()
        url = (data.get("url") or "").strip()
        title = (data.get("title") or "").strip() or None
        search_enabled = 0
        opensearch_doc_url = None
        opensearch_template = None

        if not keyword or not url:
            abort(400, "keyword and url are required")
        if any(ch.isspace() for ch in keyword):
            abort(400, "keyword cannot contain whitespace")
        if not (url.startswith("http://") or url.startswith("https://")):
            abort(400, "url must start with http:// or https://")
        discovered = opensearch.discover_opensearch_template(url)
        if discovered:
            opensearch_doc_url, opensearch_template = discovered
            search_enabled = True
        try:
            db.execute(
                """
                INSERT INTO links(keyword, url, title, search_enabled, opensearch_doc_url, opensearch_template)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (keyword, url, title, int(search_enabled), opensearch_doc_url, opensearch_template),
            )
            db.commit()
            invalidate_suggestions_cache()
        except sqlite3.IntegrityError:
            return {"error": f"keyword '{escape(keyword)}' already exists"}, 400
        return {"ok": True}

    rows = db.execute(
        "SELECT keyword, title, url, search_enabled FROM links ORDER BY keyword COLLATE NOCASE"
    ).fetchall()
    return {"links": [_serialize_link(r) for r in rows]}


@api_bp.route("/links/<keyword>", methods=["GET"])
def get_link(keyword: str):
    """Return details for a single link (case-insensitive keyword lookup)."""
    db = get_db()
    row = db.execute(
        "SELECT keyword, title, url, search_enabled FROM links WHERE keyword COLLATE NOCASE = ?",
        (keyword,),
    ).fetchone()
    if not row:
        abort(404, "link not found")
    return {"link": _serialize_link(row)}


@api_bp.route("/links/<keyword>", methods=["PUT", "PATCH"])
def update_link(keyword: str):
    """Update an existing link."""
    db = get_db()
    row = db.execute(
        "SELECT id, keyword, title, url, search_enabled FROM links WHERE keyword COLLATE NOCASE = ?",
        (keyword,),
    ).fetchone()
    if not row:
        abort(404, "link not found")

    data = _get_json_object()
    new_keyword = (data.get("keyword") or row["keyword"]).strip()
    new_url = (data.get("url") or row["url"]).strip()
    new_title = (data.get("title") or row["title"] or "").strip() or None
    new_search_enabled = False
    opensearch_doc_url = None
    opensearch_template = None

    if not new_keyword or not new_url:
        abort(400, "keyword and url are required")  # pragma: no cover
    if any(ch.isspace() for ch in new_keyword):
        abort(400, "keyword cannot contain whitespace")
    if not (new_url.startswith("http://") or new_url.startswith("https://")):
        abort(400, "url must start with http:// or https://")
    discovered = opensearch.discover_opensearch_template(new_url)
    if discovered:
        opensearch_doc_url, opensearch_template = discovered
        new_search_enabled = True

    try:
        db.execute(
            """
            UPDATE links
            SET keyword=?, url=?, title=?, search_enabled=?, opensearch_doc_url=?, opensearch_template=?
            WHERE id=?
            """,
            (
                new_keyword,
                new_url,
                new_title,
                int(new_search_enabled),
                opensearch_doc_url,
                opensearch_template,
                row["id"],
            ),
        )
        db.commit()
        invalidate_suggestions_cache()
    except sqlite3.IntegrityError:
        abort(400, f"keyword '{new_keyword}' already exists")

    return {
        "ok": True,
        "link": {
            "keyword": escape(new_keyword),
            "title": escape(new_title) if new_title is not None else None,
            "url": escape(new_url),
            "search_enabled": new_search_enabled,
        },
    }


@api_bp.route("/links/<keyword>", methods=["DELETE"])
def delete_link(keyword: str):
    """Delete a link by keyword (case-insensitive)."""
    db = get_db()
    row = db.execute(
        "SELECT id FROM links WHERE keyword COLLATE NOCASE = ?",
        (keyword,),
    ).fetchone()
    if not row:
        abort(404, "link not found")
    with db:
        db.execute("DELETE FROM links WHERE id=?", (row["id"],))
    invalidate_suggestions_cache()
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
    if request.method == "POST":
        data = _get_json_object()
        slug = (data.get("slug") or "").strip()
        name = (data.get("name") or "").strip()
        desc = (data.get("description") or "").strip() or None
        if not slug and not name:
            abort(400, "slug or name required")
        if not slug:
            slug = to_slug(name)
        if not name:
            name = slug.replace("-", " ").title()
        base_url = request.host_url.rstrip("/")
        list_url = f"{base_url}/lists/{slug}"
        title = f"List - {name}"
        try:
            with db:
                db.execute("INSERT INTO lists(slug,name,description) VALUES (?,?,?)", (slug, name, desc))
                db.execute(
                    "INSERT OR IGNORE INTO links(keyword, url, title) VALUES (?, ?, ?)",
                    (slug, list_url, title),
                )
        except sqlite3.IntegrityError:
            abort(400, "slug exists")
        invalidate_suggestions_cache()

        return {"ok": True}

    rows = db.execute("SELECT slug,name,description FROM lists ORDER BY name COLLATE NOCASE").fetchall()
    return {"lists": [dict(r) for r in rows]}


@api_bp.route("/lists/<slug>", methods=["GET", "PUT", "PATCH", "DELETE"])
def list_detail(slug: str):
    """CRUD operations for a single list (case-insensitive slug lookup)."""
    db = get_db()
    info = db.execute(
        "SELECT id, slug, name, description FROM lists WHERE slug COLLATE NOCASE = ?",
        (slug,),
    ).fetchone()

    if request.method == "GET":
        if not info:
            abort(404, "list not found")
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
            abort(404, "list not found")
        data = _get_json_object()
        new_slug = (data.get("slug") or info["slug"]).strip()
        new_name = (data.get("name") or info["name"]).strip()
        new_desc = (data.get("description") or info["description"] or "").strip() or None
        if not new_slug:
            abort(400, "slug required")  # pragma: no cover
        if not new_name:
            new_name = new_slug.replace("-", " ").title()  # pragma: no cover
        try:
            with db:
                db.execute(
                    "UPDATE lists SET slug=?, name=?, description=? WHERE id=?",
                    (new_slug, new_name, new_desc, info["id"]),
                )

                # Update the auto-created shortcut link if it exists (best effort).
                with suppress(Exception):
                    base_url = request.host_url.rstrip("/")
                    list_url = f"{base_url}/lists/{new_slug}"
                    title = f"List - {new_name}"
                    db.execute(
                        "UPDATE links SET keyword=?, url=?, title=? WHERE keyword COLLATE NOCASE = ?",
                        (new_slug, list_url, title, slug),
                    )
        except sqlite3.IntegrityError:
            return {"error": f"slug '{escape(new_slug)}' already exists"}, 400
        invalidate_suggestions_cache()

        return {
            "ok": True,
            "list": {
                "slug": escape(new_slug),
                "name": escape(new_name),
                "description": escape(new_desc) if new_desc is not None else None,
            },
        }

    # DELETE branch
    if not info:
        abort(404, "list not found")  # pragma: no cover
    with db:
        db.execute("DELETE FROM lists WHERE id=?", (info["id"],))
        with suppress(Exception):
            db.execute("DELETE FROM links WHERE keyword COLLATE NOCASE = ?", (slug,))
    invalidate_suggestions_cache()
    return {"ok": True}


@api_bp.route("/lists/<slug>/links", methods=["GET", "POST"])
def list_links(slug: str):
    """List or append links within a list."""
    db = get_db()
    info = db.execute(
        "SELECT id FROM lists WHERE slug COLLATE NOCASE = ?",
        (slug,),
    ).fetchone()
    if not info:
        abort(404, "list not found")

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

    data = _get_json_object()
    keyword = (data.get("keyword") or "").strip()
    if not keyword:
        abort(400, "keyword required")
    link = db.execute(
        "SELECT id FROM links WHERE keyword COLLATE NOCASE = ?",
        (keyword,),
    ).fetchone()
    if not link:
        abort(404, "link not found")
    with db:
        db.execute(
            "INSERT OR IGNORE INTO link_lists(link_id, list_id) VALUES (?, ?)",
            (link["id"], info["id"]),
        )
    return {"ok": True}


@api_bp.route("/lists/<slug>/links/<keyword>", methods=["DELETE"])
def remove_list_link(slug: str, keyword: str):
    """Remove a link from a list."""
    db = get_db()
    info = db.execute(
        "SELECT id FROM lists WHERE slug COLLATE NOCASE = ?",
        (slug,),
    ).fetchone()
    if not info:
        abort(404, "list not found")
    link = db.execute(
        "SELECT id FROM links WHERE keyword COLLATE NOCASE = ?",
        (keyword,),
    ).fetchone()
    if not link:
        abort(404, "link not found")
    with db:
        db.execute(
            "DELETE FROM link_lists WHERE link_id=? AND list_id=?",
            (link["id"], info["id"]),
        )
    return {"ok": True}


# Root-level endpoints registered in main.py.


def healthz():
    """Lightweight health check endpoint.

    Returns JSON {"status": "ok"} when a simple `SELECT 1` succeeds, or
    an error payload with HTTP 500 when it fails.
    """
    try:
        db = get_db()
        db.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}, 500


def export_shortcuts_csv():
    """Download all shortcuts as a CSV attachment."""
    db = get_db()
    rows = _select_links_with_lists(db)

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["keyword", "title", "url", "search_enabled", "lists"])
    for row in rows:
        writer.writerow(
            [
                row["keyword"],
                row["title"] or "",
                row["url"],
                "1" if row["search_enabled"] else "0",
                row["lists_csv"] or "",
            ]
        )

    csv_data = buffer.getvalue()
    response = Response(csv_data, content_type="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = 'attachment; filename="shortcuts.csv"'
    return response


def import_shortcuts_csv():
    """Handle CSV uploads and merge shortcuts into the database."""
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        abort(400, "Missing CSV upload")
    uploaded.stream.seek(0, os.SEEK_SET)

    db = get_db()
    _import_shortcuts_from_csv(db, uploaded)
    invalidate_suggestions_cache()
    return redirect(url_for("index"))


def opensearch_description():
    """Serve the OpenSearch description document for auto-discovery."""
    base_url = request.host_url.rstrip("/")
    search_url = f"{base_url}/go?q={{searchTerms}}"
    suggest_url = f"{base_url}/opensearch/suggest?q={{searchTerms}}"
    safe_search_url = escape(search_url, quote=True)
    safe_suggest_url = escape(suggest_url, quote=True)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">
  <ShortName>go</ShortName>
  <Description>Local shortcuts search</Description>
  <Url type="text/html" method="get" template="{safe_search_url}"/>
  <Url type="application/x-suggestions+json" template="{safe_suggest_url}"/>
  <InputEncoding>UTF-8</InputEncoding>
  <OutputEncoding>UTF-8</OutputEncoding>
</OpenSearchDescription>
"""
    return Response(xml, mimetype="application/opensearchdescription+xml")


def opensearch_suggest():
    """Return OpenSearch-style JSON suggestions for browsers supporting it."""
    raw_q = request.args.get("q") or ""
    q = sanitize_query(raw_q)
    db = get_db()
    matches = _search_suggestions(db, q)
    keywords = [item["keyword"] for item in matches]
    titles = [(item.get("title") or item["keyword"]) for item in matches]
    urls = [item["url"] for item in matches]
    payload = json.dumps([q, keywords, titles, urls])
    return Response(payload, mimetype="application/x-suggestions+json")
