from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import webbrowser
from urllib.parse import quote_plus

from flask import Flask, abort, redirect, render_template, request, url_for

from .admin import admin_bp
from .api import api_bp
from .db import DB_PATH, ensure_lists_schema, get_db
from .db import init_app as db_init_app
from .lists import lists_bp
from .utils import (
    config,
    file_url_to_path,
    is_allowed_path,
    open_path_with_os,
    render_url_template,
    sanitize_query,
    split_query,
)

try:
    import pystray  # type: ignore
    from pystray import Menu
    from pystray import MenuItem as item
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
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow is required to render the tray image")
    img = Image.new("RGBA", (W, H), bg)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, W - 6, H - 6], 12, fill=panel)
    d.ellipse([10, 22, 26, 38], fill=accent)  # simple dot
    text = "go"
    try:
        font = ImageFont.load_default()
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
    _TEMPLATES_DIR = os.path.join(sys._MEIPASS, "backend", "app", "templates")  # type: ignore[attr-defined]
else:
    _TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

app = Flask(__name__, template_folder=_TEMPLATES_DIR)
db_init_app(app)
app.register_blueprint(api_bp, url_prefix="/api")
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(lists_bp, url_prefix="/lists")


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
    # If you have the lists schema, this will include list slugs per link.
    rows = db.execute("""
        SELECT l.keyword, l.title, l.url,
               IFNULL(GROUP_CONCAT(li.slug, ', '), '') AS lists_csv
        FROM links l
        LEFT JOIN link_lists ll ON ll.link_id = l.id
        LEFT JOIN lists li ON li.id = ll.list_id
        GROUP BY l.id
        ORDER BY l.keyword COLLATE NOCASE
    """).fetchall()
    return render_template("index.html", rows=rows)


@app.route("/go")
def go():
    """Main redirector endpoint.

    Accepts `?q=<keyword>` and resolves it to a URL:
      - Exact match: 302 to the stored URL (supports http/https, file:// with safeguards)
      - Prefix/template provider: expands placeholders and redirects
      - No match: renders the suggestions page (not_found.html), optionally
        showing a fallback search link when configured.
    """
    raw = (request.args.get("q") or "").strip()
    q = sanitize_query(raw)
    if not q:
        abort(400, "Missing q")

    db = get_db()
    key, rest, words = split_query(q)
    exact = db.execute("SELECT url FROM links WHERE lower(keyword) = lower(?)", (q,)).fetchone()

    prov = None
    if not exact:
        prov = db.execute("SELECT url FROM links WHERE lower(keyword) = lower(?)", (key,)).fetchone()

    if exact and not prov:
        url = exact["url"]

        if url.startswith(("http://", "https://")):
            return redirect(url, code=302)

        if url.startswith("file://"):
            try:
                path = file_url_to_path(url)
            except Exception as e:
                return (f"Bad file URL: {e}", 400)

            # Safety: only allow local opens (keep server bound to 127.0.0.1) and/or allowlist
            if request.host.split(":")[0] not in ("127.0.0.1", "localhost") and not ALLOW_FILES:
                return (
                    "Refusing to open local files over non-localhost. Bind to 127.0.0.1 or set ALLOW_FILES.",
                    403,
                )

            if not is_allowed_path(path):
                return ("Path not allowed. Set ALLOW_FILES to include this directory.", 403)

            if not (os.path.exists(path)):
                return (f"File/folder not found: {path}", 404)

            try:
                open_path_with_os(path)
            except Exception as e:
                return (f"Failed to open: {e}", 500)

            # Show a tiny confirmation page (no redirect to file://)
            return render_template("file_open.html", path=path), 200

        return redirect(url, code=302)

    if prov:
        url_tmpl = prov["url"]
        # If it's a template (contains placeholders), render it
        if any(tok in url_tmpl for tok in ("{args", "{q}", "{1}", "{2}", "{3}")):
            final_url = render_url_template(url_tmpl, q, rest, words)
            if final_url.startswith(("http://", "https://")):
                return redirect(final_url, code=302)
            return ("Template resolved to unsupported scheme", 400)
        # Not a template: if no args, just go; if args present, ignore args and go
        if url_tmpl.startswith(("http://", "https://")):
            return redirect(url_tmpl, code=302)
        if url_tmpl.startswith("file://"):
            path = file_url_to_path(url_tmpl)
            # ... (unchanged)
            return render_template("file_open.html", path=path), 200
        return ("Unsupported URL scheme", 400)

    # Collect suggestions (prefix/substring matches on keyword/title/url)
    like = f"%{q}%"
    suggestions = db.execute(
        """
        SELECT keyword, title, url
        FROM links
        WHERE keyword LIKE ? OR (title IS NOT NULL AND title LIKE ?) OR url LIKE ?
        ORDER BY keyword COLLATE NOCASE LIMIT 10
        """,
        (like, like, like),
    ).fetchall()

    fallback_url = ""
    if FALLBACK_URL_TEMPLATE:
        fallback_url = FALLBACK_URL_TEMPLATE.format(q=quote_plus(q))

    return render_template(
        "not_found.html", q=q, suggestions=[dict(x) for x in suggestions], fallback_url=fallback_url
    ), 404


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
          title TEXT
        );
        """)
        db.commit()

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
