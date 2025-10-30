# go -- local shortcuts server

This local Flask app lets you type `go <keyword>` in your browser's address bar and jump straight to a stored URL. It uses Flask blueprints, Jinja templates, and an SQLite database behind a tiny admin UI.

## Features
- Keyword driven redirects with substring suggestions and an optional fallback search link
- URL templates with `{q}`, `{args}`, `{1}` style placeholders for provider shortcuts
- Optional local file launches guarded by an allow list of directories
- Browser admin UI for links, lists, and runtime config (no authentication; intended for localhost)
- JSON API surface for scripting link and list management
- Optional system tray icon plus a PyInstaller spec for packaging a desktop helper

## Current TODOs:
- 1.0 polish: add a search flag, lock the homepage keyword, finish API CRUD endpoints, complete README dev-install and feature docs, embed run-on-start, prepare EXE releases, wire up OpenSearch, add pytest scaffolding, and split admin/api link handlers.
- Docs & agents: create `agents.md` and restructure the top-level documentation.
- 2.0 roadmap: add admin/API authentication, separate admin flows, introduce rate limiting, harden DB usage, provide Docker packaging, and pursue performance improvements.
- 3.0 exploration: consider a Rust rewrite, expand official Linux/macOS support, and develop an enterprise-ready release.

## How it works
- Shortcuts live in SQLite at `backend/app/data/links.db` by default (configurable).
- Configure a browser search engine keyword such as `go` that points to `http://127.0.0.1:5000/go?q=%s`.
- Exact keyword matches issue a 302 redirect; provider style shortcuts expand URL templates; non matches show suggestions.
- Fallback searches come from the configured `fallback-url` string (for example DuckDuckGo or Google).
- File shortcuts (`file://...`) only open when `allow-files` is true and the target path is inside the configured `file-allow` directories.
- Runtime settings are loaded from `config.json` (generated from `config-template.txt` on first run).

## Project layout

```
backend/
  app/
    main.py              # Flask app, routes, tray integration
    db.py                # Database helpers and schema utilities
    utils.py             # Config loader, URL helpers, file safety checks
    api/                 # JSON API blueprint
    admin/               # Admin UI blueprint (links, lists, config editor)
    lists/               # List pages blueprint
    templates/           # Jinja templates for UI pages
    data/links.db        # SQLite data (created on first run/import)
  wsgi.py                # WSGI entry point for production servers
app.py                   # Compatibility shim that imports backend.app.main
config-template.txt      # Example config copied when config.json is missing
config.json              # Runtime config (git ignored)
init_db.py               # CLI helper to initialise/import the database
requirements.txt         # App dependencies (includes lint/format tooling)
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# create config.json if you do not have one yet
cp config-template.txt config.json  # Windows: copy config-template.txt config.json

# optional: create the SQLite database and lists schema up front
python init_db.py

# run the server (compat shim)
python app.py

# or run the package directly
python -m backend

# or via a WSGI server
gunicorn backend.wsgi:application
```

The server listens on `host` and `port` from `config.json` (defaults to `127.0.0.1:5000`) and stores data at the configured `db-path`.

## Configuration

Runtime settings live in `config.json` (git ignored). The file is created automatically from `config-template.txt` the first time the app boots, or you can copy the template yourself before running.

The available keys:

- `host` (str, default `127.0.0.1`): network interface for the Flask server.
- `port` (int, default `5000`): port to bind.
- `debug` (bool, default `false`): enables Flask debug mode and reloader.
- `db-path` (str, default `backend/app/data/links.db`): absolute or relative path to the SQLite database file.
- `allow-files` (bool): set to `true` to permit `file://` shortcuts when paths are in the allow list.
- `file-allow` (list of strings): absolute directories that local file links may open. Leave empty to block file opens even if `allow-files` is true.
- `fallback-url` (str, default empty): template used when no shortcut matches. Use `{q}` for the URL encoded query.

You can point the app at another config file by setting the `GO_CONFIG_PATH` environment variable before launching. The admin Config page at `/admin/config` lets you edit and save these values through the browser with validation.

## Admin tools

- `/admin`: list, add, delete, and tag shortcuts; auto creates list links.
- `/admin/config`: edit `config.json` through the browser (writes back to disk).
- `/lists`: browse lists and view individual list pages.
- `/healthz`: simple health probe for monitoring.

The admin UI has no authentication and is intended for local use only.

## Managing shortcuts

- Open `http://127.0.0.1:5000/admin` to add or delete shortcuts through the form.
- Assign comma separated list slugs via the "Set lists" action; missing lists are created automatically.
- File shortcuts should use `file://` URLs. Ensure `allow-files` is true and the target directory is listed in `file-allow`.

You can seed shortcuts from the command line with:

```bash
curl -X POST http://127.0.0.1:5000/api/links \
  -H "content-type: application/json" \
  -d '{"keyword":"cal","title":"My Calendar","url":"https://calendar.google.com"}'
```

(PowerShell users can replace the trailing backslashes with backticks or use a JSON file.)

## Import or seed data

Use `python init_db.py` to ensure the database exists. Provide a CSV export to import rows:

```bash
python init_db.py links.csv
# CSV columns: keyword,title,url
```

The script creates the base schema plus list tables so the admin UI works immediately.

## Add to browser

**Option A -- custom search engine (recommended)**

1. Create a new search engine pointing to `http://127.0.0.1:5000/go?q=%s`.
2. Set the keyword to something short like `go`.
3. Type `go keyword` to jump straight to the shortcut.

**Option B -- bookmark the home page**

1. Bookmark `http://127.0.0.1:5000/`.
2. Use the GUI to browse and manage shortcuts.

## API endpoints

- `GET /api/links` -- list all links.
- `POST /api/links` -- add a link (`{"keyword":"gh","url":"https://github.com","title":"GitHub"}`).
- `GET /api/lists` -- list lists.
- `POST /api/lists` -- add a list (`{"slug":"work","name":"Work Projects","description":"..."}`).

All responses are JSON. There is no authentication; run it on trusted networks only.

## Development

Install dependencies from `requirements.txt`, then run Ruff for linting/formatting:

```bash
ruff check backend
ruff format backend
```

You can install Ruff globally via `pipx install ruff` if you prefer not to install it in the virtual environment.

## Build an executable (PyInstaller)

Use the provided spec (bundles templates automatically):

```bash
pip install pyinstaller
pyinstaller go-server.spec
# Output ends up in dist/go-server/
```

Or build quickly without the spec (remember to add templates yourself):

```bash
pyinstaller -F -n go-server app.py --add-data "backend/app/templates;backend/app/templates"
```

When run from a bundled executable, the app writes the SQLite database under `data/links.db` next to the binary unless overridden via `config.json`.

## Notes

- The app assumes localhost usage and exposes no authentication; keep it firewalled.
- `file://` targets are only opened when both `allow-files` is true and the path is inside `file-allow`.
- Matching is case insensitive for keywords; substring suggestions consider keyword, title, and URL.
- If `pystray` and `pillow` are installed, the tray icon offers quick links to Home and Admin.

## License

MIT. See `LICENSE` for details.
