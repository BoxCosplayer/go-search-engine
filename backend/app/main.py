from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import sys
import threading
import webbrowser
import xml.etree.ElementTree as ET
from functools import lru_cache
from html.parser import HTMLParser
from io import StringIO
from urllib.parse import quote_plus, urljoin, urlparse

import httpx

try:  # pragma: no cover
    from curl_cffi import requests as curl_requests  # type: ignore
except Exception:  # pragma: no cover
    curl_requests = None  # type: ignore

try:  # pragma: no cover
    import tls_client
except Exception:  # pragma: no cover
    tls_client = None  # type: ignore

from flask import Flask, Response, abort, redirect, render_template, request, url_for

from .admin import admin_bp
from .api import api_bp
from .db import DB_PATH, ensure_lists_schema, ensure_search_flag_column, get_db
from .db import init_app as db_init_app
from .lists import lists_bp
from .utils import (
    config,
    file_url_to_path,
    is_allowed_path,
    open_path_with_os,
    sanitize_query,
)

try:
    import pystray  # type: ignore
    from pystray import Menu  # pragma: no cover
    from pystray import MenuItem as item  # pragma: no cover
except Exception:  # pragma: no cover
    pystray = None  # we'll run without a tray if deps are missing
    Menu = None  # type: ignore[assignment]
    item = None  # type: ignore[assignment]

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]

# 64x64 simple dark badge with "go"
HOST = config.host
PORT = config.port
DEBUG = config.debug
FALLBACK_URL_TEMPLATE = config.fallback_url  # e.g. "https://duckduckgo.com/?q={q}"
ALLOW_FILES = config.allow_files

OPENSEARCH_TIMEOUT = 5
OPENSEARCH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/118.0 Safari/537.36 go-search-engine/0.4"
)
_OPTIONAL_PLACEHOLDER_RE = re.compile(r"\{[^}]+\?\}")
DEFAULT_HTTP_HEADERS = {
    "User-Agent": OPENSEARCH_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="118", "Google Chrome";v="118"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
_HTTP_CLIENT = httpx.Client(
    http2=False,
    headers=DEFAULT_HTTP_HEADERS,
    timeout=httpx.Timeout(OPENSEARCH_TIMEOUT, connect=OPENSEARCH_TIMEOUT),
    follow_redirects=True,
)


class _SearchLinkParser(HTMLParser):
    """HTML parser that collects OpenSearch link hrefs."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        attr_map = {name.lower(): value or "" for name, value in attrs}
        rel = attr_map.get("rel", "")
        rel_tokens = {token.strip().lower() for token in rel.split()}
        if "search" not in rel_tokens and "search" not in rel.lower():
            return
        type_attr = attr_map.get("type", "")
        if type_attr and "opensearchdescription+xml" not in type_attr.lower():
            return
        href = attr_map.get("href")
        if href:
            self.hrefs.append(href)


def _parse_opensearch_link_hrefs(html: str) -> list[str]:
    parser = _SearchLinkParser()
    parser.feed(html)
    return parser.hrefs


def _parse_opensearch_script_hrefs(html: str) -> list[str]:
    urls: list[str] = []
    pattern = re.compile(r'opensearchurl[^"]*"([^"]+)"', re.IGNORECASE)
    for match in pattern.findall(html):
        unescaped = match.replace("\\/", "/")
        urls.append(unescaped)
    return urls


@lru_cache(maxsize=128)
def _fetch_html(url: str) -> str | None:
    resp = _http_get(url)
    if resp is None:
        return None
    encoding = resp.encoding or "utf-8"
    return resp.content.decode(encoding, errors="replace")


def _http_get(url: str) -> httpx.Response | None:
    resp: httpx.Response | None = None
    try:
        candidate = _HTTP_CLIENT.get(url)
        if candidate.status_code < 400:
            return candidate
    except Exception:  # pragma: no cover - network failure fallback
        candidate = None
    if curl_requests is not None:
        try:
            alt = curl_requests.get(
                url,
                impersonate="chrome120",
                timeout=OPENSEARCH_TIMEOUT,
                allow_redirects=True,
            )
            if alt.status_code < 400:
                return _CurlResponseAdapter(alt)
        except Exception:  # pragma: no cover - optional dependency failure
            pass
    if tls_client is not None:
        try:
            session = tls_client.Session(client_identifier="chrome120")
            alt = session.get(
                url,
                headers=DEFAULT_HTTP_HEADERS,
                timeout=OPENSEARCH_TIMEOUT,
                allow_redirects=True,
            )
            if alt.status_code < 400:
                return _TlsClientResponseAdapter(alt)
        except Exception:  # pragma: no cover - optional dependency failure
            pass
    return resp


class _CurlResponseAdapter:
    """Adapter so curl_cffi responses act like httpx responses."""

    def __init__(self, resp):
        self.status_code = resp.status_code
        self.content = resp.content
        self.encoding = resp.encoding


class _TlsClientResponseAdapter:
    """Adapter so tls-client responses act like httpx responses."""

    def __init__(self, resp):
        self.status_code = resp.status_code
        self.content = resp.content
        self.encoding = resp.encoding or "utf-8"


def _require_pillow_modules():
    """Return Pillow modules or raise when Pillow is unavailable."""
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow is required to render the tray image")
    return Image, ImageDraw, ImageFont


def _make_tray_image():
    """Create an in-memory tray icon image.

    Builds a simple 64x64 RGBA badge with a rounded rectangle and a
    "go" label in the project accent color. Used when the optional
    system tray is enabled via pystray.

    Returns:
        PIL.Image.Image: The generated icon image.
    """
    # 64x64 simple dark badge with "go"
    W = H = 64
    bg = (13, 17, 23, 255)  # #0d1117
    panel = (22, 27, 34, 255)  # #161b22
    accent = (88, 166, 255, 255)  # #58a6ff
    image_mod, draw_mod, font_mod = _require_pillow_modules()
    img = image_mod.new("RGBA", (W, H), bg)
    d = draw_mod.Draw(img)
    d.rounded_rectangle([6, 6, W - 6, H - 6], 12, fill=panel)
    d.ellipse([10, 22, 26, 38], fill=accent)  # simple dot
    text = "go"
    try:
        font = font_mod.load_default() if font_mod is not None else None
    except Exception:
        font = None
    d.text((30, 22), text, fill=accent, font=font)
    return img


def _base_dir() -> str:  # if running as a PyInstaller EXE, use the folder containing the executable
    """Return the base folder for runtime resources.

    Uses the executable directory when frozen (PyInstaller), otherwise
    the directory of this module. Keeps data files colocated with the app.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(__file__)


BASE_DIR = _base_dir()


def _resource_path(name: str) -> str:
    """Resolve a resource path for dev and frozen builds.

    Search order:
      1) Next to the running script/executable (BASE_DIR/name)
      2) Inside the PyInstaller bundle (sys._MEIPASS/name)
      3) Fallback to BASE_DIR/name

    Args:
        name: Relative file or directory name.
    """
    # 1) external next to exe/script, 2) bundled in one-file exe, 3) fallback
    p1 = os.path.join(BASE_DIR, name)
    if os.path.exists(p1):
        return p1
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        p2 = os.path.join(sys._MEIPASS, name)  # type: ignore[attr-defined]
        if os.path.exists(p2):
            return p2
    return p1


# characters to strip at end of query


def load_config():
    """Load optional JSON configuration.

    Honors GO_CONFIG_PATH when set, otherwise looks for config.json
    alongside the script/executable via _resource_path.

    Returns:
        dict: Parsed config values or an empty dict on error/missing file.
    """
    # Optional JSON file with defaults
    cfg_path = os.environ.get("GO_CONFIG_PATH") or _resource_path("config.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):  # pragma: no cover
    _TEMPLATES_DIR = _resource_path(os.path.join("backend", "app", "templates"))
else:
    _TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

app = Flask(__name__, template_folder=_TEMPLATES_DIR)
db_init_app(app)
app.register_blueprint(api_bp, url_prefix="/api")
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(lists_bp, url_prefix="/lists")


def _search_suggestions(db, term: str):
    """Return best-effort search suggestions for a query term."""
    term = (term or "").strip()
    if not term:
        return []
    like = f"%{term}%"
    rows = db.execute(
        """
        SELECT keyword, title, url
        FROM links
        WHERE keyword LIKE ? OR (title IS NOT NULL AND title LIKE ?) OR url LIKE ?
        ORDER BY keyword COLLATE NOCASE LIMIT 10
        """,
        (like, like, like),
    ).fetchall()
    return [dict(row) for row in rows]


def _redirect_to_url(url: str):
    if url.startswith(("http://", "https://")):
        return redirect(url, code=302)

    if url.startswith("file://"):
        try:
            path = file_url_to_path(url)
        except Exception as e:
            return (f"Bad file URL: {e}", 400)

        if request.host.split(":")[0] not in ("127.0.0.1", "localhost") and not ALLOW_FILES:
            return (
                "Refusing to open local files over non-localhost. Bind to 127.0.0.1 or set ALLOW_FILES.",
                403,
            )

        if not is_allowed_path(path):
            return ("Path not allowed. Set ALLOW_FILES to include this directory.", 403)

        if not os.path.exists(path):
            return (f"File/folder not found: {path}", 404)

        try:
            open_path_with_os(path)
        except Exception as e:
            return (f"Failed to open: {e}", 500)

        return render_template("file_open.html", path=path), 200

    return redirect(url, code=302)


def _opensearch_document_url(link_url: str) -> str | None:
    parsed = urlparse(link_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.path.lower().endswith(".xml"):
        return link_url
    base = f"{parsed.scheme}://{parsed.netloc}/"
    return urljoin(base, "opensearch.xml")


def _candidate_opensearch_document_urls(link_url: str) -> list[str]:
    parsed = urlparse(link_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return []
    base = f"{parsed.scheme}://{parsed.netloc}"
    docs: list[str] = []
    seen: set[str] = set()

    def add(url: str | None) -> None:
        if url and url not in seen:
            seen.add(url)
            docs.append(url)

    add(_opensearch_document_url(link_url))
    add(urljoin(link_url, "opensearch.xml"))
    add(urljoin(base + "/", "opensearch.xml"))
    add(urljoin(base + "/", ".well-known/opensearch.xml"))

    html_sources = {link_url, base + "/"}
    for html_url in html_sources:
        html = _fetch_html(html_url)
        if not html:
            continue
        for href in _parse_opensearch_link_hrefs(html):
            add(urljoin(html_url, href))
        for href in _parse_opensearch_script_hrefs(html):
            add(urljoin(html_url, href))
    return docs


def _download_opensearch_document(doc_url: str) -> str:
    resp = _http_get(doc_url)
    if resp is None:  # pragma: no cover - network failure fallback
        raise RuntimeError("failed to download OpenSearch descriptor")
    encoding = resp.encoding or "utf-8"
    return resp.content.decode(encoding, errors="replace")


def _extract_search_template(xml_text: str) -> str | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    for url_el in root.findall(".//{*}Url"):
        template = url_el.attrib.get("template")
        if not template:
            continue
        method = url_el.attrib.get("method", "get").lower()
        if method != "get":
            continue
        mime = url_el.attrib.get("type", "text/html").lower()
        if mime not in {"text/html", "application/xhtml+xml"}:
            continue
        if "searchterms" not in template.lower():
            continue
        return template
    return None


@lru_cache(maxsize=128)
def _get_opensearch_template(doc_url: str) -> str | None:
    try:
        xml_text = _download_opensearch_document(doc_url)
    except Exception:
        return None
    return _extract_search_template(xml_text)


def _build_search_url(doc_url: str, template: str, terms: str) -> str | None:
    encoded = quote_plus(terms)
    replaced = False
    for placeholder in ("{searchTerms}", "{searchTerms?}", "{searchterms}", "{searchterms?}"):
        if placeholder in template:
            template = template.replace(placeholder, encoded)
            replaced = True
    if not replaced:
        return None
    template = _OPTIONAL_PLACEHOLDER_RE.sub("", template)
    return urljoin(doc_url, template)


def _lookup_opensearch_search_url(link_url: str, terms: str) -> str | None:
    if not terms:
        return None
    for doc_url in _candidate_opensearch_document_urls(link_url):
        template = _get_opensearch_template(doc_url)
        if not template:
            continue
        search_url = _build_search_url(doc_url, template, terms)
        if search_url:
            return search_url
    return None


def _handle_bang_query(db, query: str):
    if not query.startswith("!"):
        return None
    remainder = query[1:].strip()
    if not remainder:
        return None
    parts = remainder.split(maxsplit=1)
    keyword = parts[0]
    search_terms = parts[1] if len(parts) > 1 else ""
    if not keyword:  # pragma: no cover - defensive guard
        return None
    row = db.execute(
        "SELECT url, search_enabled FROM links WHERE lower(keyword)=lower(?)",
        (keyword,),
    ).fetchone()
    if not row:
        return None
    if not row["search_enabled"] or not search_terms:
        return _redirect_to_url(row["url"])
    search_url = _lookup_opensearch_search_url(row["url"], search_terms)
    if not search_url:
        return _redirect_to_url(row["url"])
    return _redirect_to_url(search_url)


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
    for row in reader:
        keyword = (row.get("keyword") or "").strip()
        url = (row.get("url") or "").strip()
        if not keyword or not url:
            continue
        title = (row.get("title") or "").strip()
        raw_flag = (row.get("search_enabled") or "").strip().lower()
        search_enabled = 1 if raw_flag in {"1", "true", "yes", "y", "on"} else 0

        existing_keyword = db.execute(
            "SELECT id FROM links WHERE lower(keyword)=lower(?)",
            (keyword,),
        ).fetchone()
        existing_url = db.execute(
            "SELECT id FROM links WHERE lower(url)=lower(?)",
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

        duplicates = db.execute(
            "SELECT id FROM links WHERE lower(url)=lower(?) AND id <> ?",
            (url, link_id),
        ).fetchall()
        for duplicate in duplicates:
            _delete_link(db, duplicate["id"])

        lists_field = row.get("lists") or ""
        slugs = [slug.strip() for slug in lists_field.split(",") if slug.strip()]
        list_ids: list[int] = []
        for slug in slugs:
            list_row = db.execute(
                "SELECT id FROM lists WHERE lower(slug)=lower(?)",
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
            db.execute(
                "INSERT OR IGNORE INTO link_lists(link_id, list_id) VALUES (?, ?)",
                (link_id, list_id),
            )

        if not list_ids:
            db.execute("DELETE FROM link_lists WHERE link_id=?", (link_id,))
        else:
            placeholders = ",".join("?" for _ in list_ids)
            db.execute(
                f"DELETE FROM link_lists WHERE link_id=? AND list_id NOT IN ({placeholders})",
                (link_id, *list_ids),
            )

    return inserted + updated


@app.route("/healthz")
def healthz():
    """Lightweight health check endpoint.

    Returns JSON {"status": "ok"} when a simple `SELECT 1` succeeds, or
    an error payload with HTTP 500 when it fails.
    """
    # Basic health endpoint
    try:
        db = get_db()
        db.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}, 500


@app.route("/")
def index():
    """Render the home page or redirect a search query.

    - If `q` is present (e.g., `/?q=gh`), redirect to `/go?q=...`.
    - Otherwise, render the index view listing known links.
    """
    query = (request.args.get("q") or "").trim() if hasattr(str, "trim") else (request.args.get("q") or "").strip()
    if query:
        return redirect(url_for("go", q=query), code=302)
    db = get_db()
    ensure_lists_schema(db)
    rows = _select_links_with_lists(db)
    return render_template("index.html", rows=rows)


@app.route("/export/shortcuts.csv")
def export_shortcuts_csv():
    """Download all shortcuts as a CSV attachment."""
    db = get_db()
    ensure_lists_schema(db)
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


@app.post("/import/shortcuts")
def import_shortcuts_csv():
    """Handle CSV uploads and merge shortcuts into the database."""
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        abort(400, "Missing CSV upload")
    uploaded.stream.seek(0, os.SEEK_SET)

    db = get_db()
    ensure_lists_schema(db)
    _import_shortcuts_from_csv(db, uploaded)
    db.commit()
    return redirect(url_for("index"))


@app.route("/go")
def go():
    """Main redirector endpoint.

    Accepts `?q=<keyword>` and resolves it to a URL:
      - Exact match: 302 to the stored URL (supports http/https, file:// with safeguards)
      - No match or multi-term query: renders the suggestions page (not_found.html), optionally
        showing a fallback search link when configured.
    """
    raw = (request.args.get("q") or "").strip()
    q = sanitize_query(raw)
    if not q:
        abort(400, "Missing q")

    db = get_db()
    bang_response = _handle_bang_query(db, q)
    if bang_response is not None:
        return bang_response

    if any(ch.isspace() for ch in q):
        suggestions = _search_suggestions(db, q)
        fallback_url = ""
        if FALLBACK_URL_TEMPLATE:
            fallback_url = FALLBACK_URL_TEMPLATE.format(q=quote_plus(q))
        return (
            render_template("not_found.html", q=q, suggestions=suggestions, fallback_url=fallback_url),
            404,
        )

    exact = db.execute("SELECT url FROM links WHERE lower(keyword) = lower(?)", (q,)).fetchone()

    if exact:
        return _redirect_to_url(exact["url"])

    # Collect suggestions (prefix/substring matches on keyword/title/url)
    suggestions = _search_suggestions(db, q)

    fallback_url = ""
    if FALLBACK_URL_TEMPLATE:
        fallback_url = FALLBACK_URL_TEMPLATE.format(q=quote_plus(q))

    return (
        render_template("not_found.html", q=q, suggestions=suggestions, fallback_url=fallback_url),
        404,
    )


@app.route("/opensearch.xml")
def opensearch_description():
    """Serve the OpenSearch description document for auto-discovery."""
    base_url = request.host_url.rstrip("/")
    search_url = f"{base_url}/go?q={{searchTerms}}"
    suggest_url = f"{base_url}/opensearch/suggest?q={{searchTerms}}"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">
  <ShortName>go</ShortName>
  <Description>Local shortcuts search</Description>
  <Url type="text/html" method="get" template="{search_url}"/>
  <Url type="application/x-suggestions+json" template="{suggest_url}"/>
  <InputEncoding>UTF-8</InputEncoding>
  <OutputEncoding>UTF-8</OutputEncoding>
</OpenSearchDescription>
"""
    return Response(xml, mimetype="application/opensearchdescription+xml")


@app.route("/opensearch/suggest")
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


# ---- Minimal admin UI (no auth, intended for localhost only) ----


if __name__ == "__main__":  # pragma: no cover
    base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(__file__)
    os.makedirs(os.path.join(base_dir, "data"), exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          keyword TEXT NOT NULL UNIQUE,
          url TEXT NOT NULL,
          title TEXT,
          search_enabled INTEGER NOT NULL DEFAULT 0
        );
        """)
        db.commit()
        ensure_search_flag_column(db)

    def _run_server():
        """Run the Flask development server (no reloader)."""
        app.run(host=HOST, port=PORT, debug=DEBUG, use_reloader=False)

    t = threading.Thread(target=_run_server, daemon=True)
    t.start()

    if pystray is not None:
        base_url = f"http://{HOST}:{PORT}"

        def open_home(icon, _):
            webbrowser.open(f"{base_url}/")

        def open_admin(icon, _):
            webbrowser.open(f"{base_url}/admin")

        def quit_app(icon, _):
            icon.visible = False
            os._exit(0)

        image = _make_tray_image()
        menu = Menu(
            item(f"Running on {HOST}:{PORT}", None, enabled=False),
            item("Open Home", open_home),
            item("Open Admin", open_admin),
            item("Quit", quit_app),
        )

        tray = pystray.Icon("go-server", image, "go-server", menu)
        tray.run()
    else:
        t.join()
