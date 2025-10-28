# go – local shortcuts server

This local Flask app lets you type `go <keyword>` in your browser's address bar and jump straight to a stored URL. It uses clean packages, Blueprints, and Jinja templates, with a consistent database location and optional system tray.

## How it works

- You create shortcuts in a local SQLite database mapping a `keyword` → `URL` (optionally a `title`).
- Your browser sends the search term to `http://127.0.0.1:5000/go?q=%s`.
- The server looks up the keyword:
  - **Exact match**: 302 redirect to the saved URL.
  - **No exact match**: shows a small page with suggestions from substring matches. If `GO_FALLBACK_URL_TEMPLATE` is set, it shows a hint of a fallback search URL.

## Project layout

```
backend/
  app/
    main.py              # app init, index, /go, healthz
    db.py                # DB connection + migration helper
    utils.py             # query/url/file helpers
    api/                 # JSON API blueprint
    admin/               # Admin UI blueprint
    lists/               # List pages blueprint
    templates/           # Jinja templates (index, admin, lists, not-found, etc.)
    data/links.db        # SQLite DB (new canonical location)
  wsgi.py                # WSGI entrypoint: backend.wsgi:application

# Compatibility shim
app.py                   # runs backend.app.main for old entrypoints

# Dev tooling
requirements.txt         # runtime deps
requirements-dev.txt     # dev tooling (ruff)
.ruff.toml               # lint/format config
```

Notes:
- On startup, the app migrates an old root `data/links.db` to `backend/app/data/links.db` if present.
- HTML previously inline in `main.py` is extracted to `backend/app/templates/`.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# configure ip address and port in config.py

{
    "host": "ipaddress" # Default: 127.0.0.100
    "port": portnum, # Default: 34000
}

# run the server (compat shim)
python app.py

# or run the package
python -m backend

# or via a WSGI server (example)
gunicorn backend.wsgi:application
```

By default it listens on `127.0.0.1:5000` and stores data in `backend/app/data/links.db`.

## Add to Browser (no extension needed)

**Option A – Custom search engine entry (recommended):**

1. Add a search engine
2. add keyword "go"
3. add url http://[IPAddress]:5000/?q=%s (default: http://127.0.0.1:5000/?q=%s)
4. Type in "go [keyword]" to access the homepage

**Option B – Bookmark Home page:**

1. Create a new bookmark with URL: `http://127.0.0.1:5000/`
2. Access all features via the GUI

## Managing shortcuts

- Open `http://127.0.0.1:5000/admin` for a tiny UI to add/delete entries.
- Or use the JSON API:

```bash
curl -X POST http://127.0.0.1:5000/api/links \
  -H "content-type: application/json" \
  -d '{"keyword":"cal","title":"My Calendar","url":"https://calendar.google.com"}'
```

List all links:

```bash
curl http://127.0.0.1:5000/api/links
```

## Environment variables

- `GO_DB_PATH` – path to the SQLite DB (default: `backend/app/data/links.db`)
- `GO_FALLBACK_URL_TEMPLATE` – optional template for non-matches, e.g. `https://duckduckgo.com/?q={q}`
- `PORT` – port to bind (default: `5000`)
- `FLASK_DEBUG` – set to `1` for auto-reload & debug
- `GO_FILE_ALLOW` – semicolon-separated absolute directories allowed for `file://` opens
  - Example (Windows): `GO_FILE_ALLOW=C:\\Users\\you;D:\\Shared`
  - Example (macOS/Linux): `GO_FILE_ALLOW=/Users/you;/srv/shared`

Security: Opening `file://` targets is only allowed from localhost or when `GO_FILE_ALLOW` explicitly allows the path.

## API endpoints

- `GET /api/links` – list links
- `POST /api/links` – add link: `{ "keyword": "gh", "url": "https://github.com", "title": "GitHub" }`
- `GET /api/lists` – list lists
- `POST /api/lists` – add list: `{ "slug": "work", "name": "Work Projects", "description": "..." }`

## Admin & Lists UIs

- Admin UI: `/admin` (add/delete links, edit list tags)
- Lists index: `/lists`
- List page: `/lists/<slug>`

## Lint and format (ruff)

Install dev tools and run lint/format:

```bash
pip install -r requirements.txt

# Lint
ruff check backend

# Format
ruff format backend
```

Tip: You can also install ruff globally via `pipx install ruff`.

## Build an executable (PyInstaller)

Two options:

- Use the provided spec (includes templates):

```bash
pip install pyinstaller
pyinstaller go-server.spec
# Output binary will be under dist/go-server/
```

- Or quick build without spec:

```bash
pyinstaller -F -n go-server app.py 
# Note: without the spec, you must include templates manually via --add-data.
# Example (Windows PowerShell):
#   pyinstaller -F -n go-server app.py --add-data "backend/app/templates;backend/app/templates"
```

Runtime notes:
- The app writes the SQLite DB under `data/links.db` next to the executable by default (or `GO_DB_PATH`).
- On first run, it will create the DB and tables if missing.

## Notes

- The admin UI has **no auth** and is meant for `localhost` use only.
- URLs must start with `http://` or `https://` to avoid unsafe schemes.
- Matching is case-insensitive for exact keyword matches; suggestions use substring matches across keyword/title/url.
- The tray icon (optional) requires `pystray` and `pillow` (already listed in `requirements.txt`).

## License

MIT — see `LICENSE` for details.
