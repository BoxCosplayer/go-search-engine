from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
import threading
import webbrowser
from functools import lru_cache, wraps
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from defusedxml import ElementTree as ET

try:  # pragma: no cover
    from curl_cffi import requests as curl_requests  # type: ignore
except Exception:  # pragma: no cover
    curl_requests = None  # type: ignore

try:  # pragma: no cover
    import tls_client
except Exception:  # pragma: no cover
    tls_client = None  # type: ignore

from flask import Flask, abort, redirect, render_template, request, url_for

from .admin import admin_bp
from .admin.auth import require_admin_auth
from .api import (
    _search_suggestions,
    _select_links_with_lists,
    api_bp,
    export_shortcuts_csv,
    healthz,
    import_shortcuts_csv,
    opensearch_description,
    opensearch_suggest,
)
from .db import DB_PATH, ensure_search_flag_column, get_db
from .db import init_app as db_init_app
from .lists import lists_bp
from .logging_setup import configure_logging
from .utils import (
    config,
    file_url_to_path,
    get_log_level,
    get_log_path,
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

logger = logging.getLogger(__name__)

_logging_configured = False
_logging_log_path = ""
_logging_log_level = ""


def _ensure_logging():
    global _logging_configured
    global _logging_log_level
    global _logging_log_path
    current_path = str(get_log_path())
    current_level = get_log_level().strip().upper()
    if not _logging_configured or current_path != _logging_log_path or current_level != _logging_log_level:
        configure_logging()
        _logging_configured = True
        _logging_log_path = current_path
        _logging_log_level = current_level


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


def _strip_optional_placeholders(template: str) -> str:
    """Remove optional OpenSearch placeholders like "{foo?}" without regex backtracking."""
    if "{" not in template:
        return template

    out: list[str] = []
    pending: list[str] | None = None

    for ch in template:
        if pending is None:
            if ch == "{":
                pending = ["{"]
            else:
                out.append(ch)
            continue

        pending.append(ch)
        if ch != "}":
            continue

        if len(pending) > 2 and pending[-2] == "?":
            pending = None
            continue

        out.extend(pending)
        pending = None

    if pending is not None:
        out.extend(pending)

    return "".join(out)


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
    except Exception as exc:  # pragma: no cover - network failure fallback
        logger.debug("Primary httpx request failed", exc_info=exc)
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
        except Exception as exc:  # pragma: no cover - optional dependency failure
            logger.debug("curl_cffi request failed", exc_info=exc)
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
        except Exception as exc:  # pragma: no cover - optional dependency failure
            logger.debug("tls-client request failed", exc_info=exc)
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


@app.before_request
def _configure_logging_once():
    _ensure_logging()


def _admin_only(view_func):
    @wraps(view_func)
    def _wrapped(*args, **kwargs):
        auth_result = require_admin_auth()
        if auth_result is not None:
            return auth_result
        return view_func(*args, **kwargs)

    return _wrapped


app.register_blueprint(api_bp, url_prefix="/api")
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(lists_bp, url_prefix="/lists")
app.add_url_rule("/healthz", view_func=healthz)
app.add_url_rule("/export/shortcuts.csv", view_func=_admin_only(export_shortcuts_csv))
app.add_url_rule("/import/shortcuts", view_func=_admin_only(import_shortcuts_csv), methods=["POST"])
app.add_url_rule("/opensearch.xml", view_func=opensearch_description)
app.add_url_rule("/opensearch/suggest", view_func=opensearch_suggest)


def _redirect_to_url(url: str):
    if url.startswith(("http://", "https://")):
        return redirect(url, code=302)

    if url.startswith("file://"):
        remote = request.remote_addr or "unknown"
        try:
            path = file_url_to_path(url)
        except Exception as e:
            logger.warning("File access rejected (bad URL) url=%s remote=%s err=%s", url, remote, e)
            return (f"Bad file URL: {e}", 400)

        logger.info("File access requested path=%s remote=%s", path, remote)

        host = request.host.split(":")[0]
        if host not in ("127.0.0.1", "localhost") and not ALLOW_FILES:
            logger.warning("File access blocked (non-local host) host=%s path=%s remote=%s", host, path, remote)
            return (
                "Refusing to open local files over non-localhost. Bind to 127.0.0.1 or set ALLOW_FILES.",
                403,
            )

        if not is_allowed_path(path):
            logger.warning("File access blocked (path not allowed) path=%s remote=%s", path, remote)
            return ("Path not allowed. Set ALLOW_FILES to include this directory.", 403)

        if not os.path.exists(path):
            logger.warning("File access failed (missing) path=%s remote=%s", path, remote)
            return (f"File/folder not found: {path}", 404)

        try:
            open_path_with_os(path)
        except Exception as e:
            logger.exception("File access failed (open error) path=%s remote=%s", path, remote)
            return (f"Failed to open: {e}", 500)

        logger.info("File access opened path=%s remote=%s", path, remote)
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
    template = _strip_optional_placeholders(template)
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
        "SELECT url, search_enabled FROM links WHERE keyword COLLATE NOCASE = ?",
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


@app.route("/")
def index():
    """Render the home page or redirect a search query.

    - If `q` is present (e.g., `/?q=gh`), redirect to `/go?q=...`.
    - Otherwise, render the index view listing known links.
    """
    query = (request.args.get("q") or "").strip()
    if query:
        return redirect(url_for("go", q=query), code=302)
    db = get_db()
    rows = _select_links_with_lists(db)
    return render_template("index.html", rows=rows)


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

    exact = db.execute(
        "SELECT url FROM links WHERE keyword COLLATE NOCASE = ?",
        (q,),
    ).fetchone()

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


# ---- Minimal admin UI (no auth, intended for localhost only) ----


if __name__ == "__main__":  # pragma: no cover
    _ensure_logging()
    base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(__file__)
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          keyword TEXT NOT NULL UNIQUE COLLATE NOCASE,
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
