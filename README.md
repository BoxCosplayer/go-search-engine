# go -- local shortcuts server

This local Flask app lets you type `go <keyword>` in your browser's address bar and jump straight to a stored URL. It uses Flask blueprints, Jinja templates, and an SQLite database behind a tiny admin UI.

## Features
- Keyword driven redirects with substring suggestions and an optional fallback search link
- Browser OpenSearch provider for one-click omnibox integration
- Optional search bangs: mark a shortcut as searchable and use `go !keyword {terms}` to hand the query to the site's OpenSearch template.
- Optional local file launches guarded by an allow list of directories
- Browser admin UI for links, lists, and runtime config (no authentication; intended for localhost)
- JSON API surface for scripting link and list management
- Optional system tray icon plus a PyInstaller spec for packaging a desktop helper

## Current TODOs:
- 1.0 polish: lock the homepage keyword, finish API CRUD endpoints, complete README dev-install and feature docs, embed run-on-start, prepare EXE releases, wire up OpenSearch, add pytest scaffolding, and split admin/api link handlers.
- Docs & agents: create `agents.md` and restructure the top-level documentation.
- 2.0 roadmap: add admin/API authentication, separate admin flows, introduce rate limiting, harden DB usage, provide Docker packaging, and pursue performance improvements.
- 3.0 exploration: consider a Rust rewrite, expand official Linux/macOS support, and develop an enterprise-ready release.

## How it works
- Shortcuts live in SQLite at `backend/app/data/links.db` by default (configurable).
- Configure a browser search engine keyword such as `go` that points to `http://127.0.0.1:5000/go?q=%s`.
- Exact keyword matches issue a 302 redirect. Non matches show suggestions.
- Prefix a shortcut with `!` (for example `go !gh issues`) when its search flag is enabled to run the site's OpenSearch query. Without the flag the request falls back to the shortcut's default target.
- Fallback searches come from the configured `fallback-url` string (for example DuckDuckGo or Google).
- File shortcuts (`file://...`) only open when `allow-files` is true and the target path is inside the configured `file-allow` directories.
- Runtime settings are loaded from `config.json` (generated from `config-template.txt` on first run).

## Browser OpenSearch integration
### Search bangs, OpenSearch, and hostile endpoints

Turning on the `search_enabled` flag for a shortcut lets you run `go !keyword cats` and have the server inspect the target site’s OpenSearch descriptor. This works great for sites that expose `/opensearch.xml` or `<link rel="search">` without additional challenges (e.g., GitHub, Wikipedia, internal Confluence).

A few public sites actively block automated fetches (notably stackoverflow.com and other Cloudflare-backed properties). When the descriptor can’t be retrieved, the bang falls back to the stored URL, which usually lands you on the home page. For those “hostile” endpoints, create the shortcut with an explicit search template instead: `https://stackoverflow.com/search?q={q}`. Leave the bang flag on, and the server will just substitute `{q}` without trying to fetch OpenSearch.

### Search bangs, OpenSearch, and hostile endpoints

Turning on the `search_enabled` flag for a shortcut lets you run `go !keyword cats` and have the server inspect the target site’s OpenSearch descriptor. This works great for sites that expose `/opensearch.xml` or `<link rel="search">` without additional challenges (e.g., GitHub, Wikipedia, internal Confluence).

A few public sites actively block automated fetches (notably stackoverflow.com and other Cloudflare-backed properties). When the descriptor can’t be retrieved, the bang falls back to the stored URL, which usually lands you on the home page. For those “hostile” endpoints, create the shortcut with an explicit search template instead: `https://stackoverflow.com/search?q={q}`. Leave the bang flag on, and the server will just substitute `{q}` without trying to fetch OpenSearch.
- The app advertises `/opensearch.xml`, so supporting browsers (Firefox, some Chromium forks) surface an â€œAdd goâ€ button automatically. Accept it to map the omnibox keyword to the server.
- Chrome/Edge still allow manual configuration: add a custom search engine pointing to `http://127.0.0.1:5000/go?q=%s` with keyword `go`.
- The optional `/opensearch/suggest` endpoint returns live completions for browsers that request OpenSearch suggestions (currently Firefox), backed by the same substring matching used on the not-found page.

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
- `run-on-startup` (bool, default `false`): exposes a preference for launching the packaged helper when the OS boots (consumed by the desktop tray build).
- `fallback-url` (str, default empty): template used when no shortcut matches. Use `{q}` for the URL encoded query.

You can point the app at another config file by setting the `GO_CONFIG_PATH` environment variable before launching. The admin Config page at `/admin/config` lets you edit and save these values through the browser with validation.

## Admin tools

- `/admin`: list, add, edit, delete, and tag shortcuts; auto creates list links.
- `/admin/config`: edit `config.json` through the browser (writes back to disk).
- `/lists`: browse lists and view individual list pages.
- `/healthz`: simple health probe for monitoring.

The admin UI has no authentication and is intended for local use only.

## Managing shortcuts

- Open `http://127.0.0.1:5000/admin` to add or delete shortcuts through the form.
- Use the Edit button on an existing row to tweak keywords, titles, or URLs; the form is pre-filled for convenience.
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
# CSV columns: keyword,title,url,search_enabled,lists
```

The script creates the base schema plus list tables so the admin UI works immediately.
When importing, rows are matched by keyword or URL; newer entries overwrite existing shortcuts and the URL must be unique after the import.

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
- `POST /api/links` -- add a link (`{"keyword":"gh","url":"https://github.com","title":"GitHub","search_enabled":true}`; the last flag is optional and defaults to `false`).
- `GET /api/links/<keyword>` -- fetch a single link by keyword (case-insensitive).
- `PUT /api/links/<keyword>` -- update keyword/title/url for an existing link.
- `DELETE /api/links/<keyword>` -- remove a link.
- `GET /api/lists` -- list lists.
- `POST /api/lists` -- add a list (`{"slug":"work","name":"Work Projects","description":"..."}`).
- `GET /api/lists/<slug>` -- fetch list metadata with its member links.
- `PUT /api/lists/<slug>` / `PATCH /api/lists/<slug>` -- update slug/name/description.
- `DELETE /api/lists/<slug>` -- delete a list (link memberships cascade).
- `GET /api/lists/<slug>/links` -- list link memberships for a list.
- `POST /api/lists/<slug>/links` -- add an existing link to a list (`{"keyword":"..."}`).
- `DELETE /api/lists/<slug>/links/<keyword>` -- remove a link from a list.

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

## How to Contribute

1. **Humans**
   - Read the README and `todos.md` to see current priorities.
   - Run `python -m venv .venv` (or `.\.venv\Scripts\activate` on Windows) and `pip install -r requirements.txt`.
   - Use `.\.venv\Scripts\python.exe -m coverage run -m pytest` (Windows) or `python -m coverage run -m pytest` (Linux/macOS) to make sure all tests pass; `coverage report --fail-under=100` must hold green before you ship changes.
   - Prefer focused commits with matching updates to docs (`README.md`, `CHANGELOG.md`, `todos.md`) when behavior shifts.
   - Keep lint tidy with `ruff check` / `ruff format`. They run fast and match CI.

2. **Automation / agents**
   - Start by reading `agents.md`; it spells out the structure, testing expectations, and safe-edit guidelines tailored to this repo.
   - When scripting edits, reuse the helper functions already in the blueprint modules and respect the re-export patterns described there.

