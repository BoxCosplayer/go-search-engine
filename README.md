# go -- local shortcuts server

This Flask application lets you register memorable keywords, then jump to the right destination by typing `go <keyword>` (or `go !keyword cats`) in your browser's address bar. It ships with a lightweight admin UI, a JSON API, and optional desktop packaging.

## Features
- Keyword-driven redirects with substring suggestions and an optional fallback search link
- Browser OpenSearch provider for omnibox integration
- Optional search bangs: mark a shortcut as searchable and use `go !keyword {terms}` to proxy the target site's query template
- Optional local file launches guarded by an allow list of directories
- Browser admin UI for links, lists, and runtime config (no authentication; intended for localhost)
- JSON API surface for scripting link and list management
- Optional system tray icon plus a PyInstaller spec for packaging a desktop helper

## Quick start

### Use the latest release (EXE)

1. Download the most recent asset from the project's Releases page (for example `go-server-windows.zip`).
2. Extract the archive; inside you'll find `go-server.exe`, `config-template.txt`, and supporting files.
3. Double-click `go-server.exe`. On first launch the app copies `config-template.txt` to `config.json` if it is missing, then starts on `http://127.0.0.1:5000/`.
4. Edit `config.json` (created next to the executable) to adjust host, port, or database location, then restart the binary.
5. Browse to `http://127.0.0.1:5000/admin` to add your first shortcuts or lists.

The bundled build writes its SQLite data to `data/links.db` in the same directory as the executable unless you override `db-path` in `config.json`.

### Run in Docker

#### Linux containers (Gunicorn)

1. Pull the published image (`ghcr.io/<your-github-org-or-user>/go-server:latest`) or build it locally:
   ```bash
   docker build -f docker/Dockerfile.linux -t go-server:linux .
   ```
2. Run it with a bind mount or named volume for `/data` (config + SQLite live there) and expose the HTTP port:
   ```bash
   docker run --rm -p 5000:5000 -v go-data:/data ghcr.io/<owner>/go-server:latest
   ```
3. The Bash entrypoint copies `config-template.txt` into `/data/config.json` on first start, rewrites `host`, `port`, and `db-path` when needed, and then boots Gunicorn via `backend.wsgi:application`.

A note on naming: replace `<owner>` with the GitHub org/user that hosts this repository (CI publishes tags to `ghcr.io/<owner>/go-server:<version>` plus `:latest`).

A compose stack is included for repeatable local setups:

```bash
docker compose up --build
```

Environment variables accepted by both Linux and Windows containers:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GO_CONFIG_PATH` | `/data/config.json` (Linux) / `C:\data\config.json` (Windows) | Location of the runtime config file. |
| `GO_DB_PATH` | `/data/links.db` / `C:\data\links.db` | SQLite destination written into `config.json`. |
| `GO_HOST` | `127.0.0.1` | Network interface Gunicorn/EXE should bind to. |
| `GO_PORT` | `5000` | External port exposed by the container. |
| `GO_GUNICORN_WORKERS` | `2` | (Linux image) Worker processes for Gunicorn. |
| `GO_GUNICORN_TIMEOUT` | `60` | (Linux image) Request timeout for Gunicorn, in seconds. |
| `GO_GUNICORN_EXTRA_ARGS` | *(empty)* | (Linux image) Extra CLI switches appended to the default Gunicorn command. |

Override any of these at `docker run`/compose time to match your environment.

#### Windows containers (bundled EXE)

1. Switch Docker Desktop to **Windows container** mode.
2. Build the image (multi-stage PyInstaller build):
   ```powershell
   docker build -t go-server:exe .
   ```
3. Launch the container and persist data under `C:\data`:
   ```powershell
   docker run --rm -p 5000:5000 -v go-data:C:\data go-server:exe
   ```

Mount existing config/database files in the same way as before; the PowerShell entrypoint now honors the same `GO_HOST`, `GO_PORT`, and `GO_DB_PATH` overrides as the Linux image.

### Development install

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# seed config.json on first run
cp config-template.txt config.json  # Windows: copy config-template.txt config.json

# ensure the SQLite schema exists (optional import step described below)
python init_db.py

# launch the development server
python app.py
```

The development server binds to the `host` and `port` defined in `config.json` (defaults to `127.0.0.1:5000`) and stores data at the configured `db-path`.

Run the tests before shipping changes:

```bash
python -m coverage run -m pytest            # Windows: .\.venv\Scripts\python.exe -m coverage run -m pytest
coverage report --fail-under=100
ruff check backend
ruff format backend
```

## Browser integration

- Configure a custom search engine (Chrome/Edge) or accept the "Add go" prompt (Firefox/compatible Chromium forks) pointing to `http://127.0.0.1:5000/go?q=%s` with keyword `go`.
- Enable the `search_enabled` flag on a shortcut to run `go !keyword cats`. For sites that block OpenSearch descriptors (e.g., Stack Overflow), set a manual template such as `https://stackoverflow.com/search?q={q}`.
- Optional endpoints `/opensearch.xml` and `/opensearch/suggest` help browsers discover the provider and surface live suggestions.

## Configuration

Runtime settings live in `config.json` (git ignored). The file is created automatically from `config-template.txt` the first time the app boots, or you can copy the template yourself before running.

Available keys:

- `host` (str, default `127.0.0.1`): network interface for the Flask server.
- `port` (int, default `5000`): port to bind.
- `debug` (bool, default `false`): enables Flask debug mode and reloader.
- `db-path` (str, default `backend/app/data/links.db`): absolute or relative path to the SQLite database.
- `allow-files` (bool): allow launching `file://` shortcuts when the target path is in the allow list.
- `file-allow` (list of strings): absolute directories that local file links may open. Leave empty to block file opens even if `allow-files` is true.
- `fallback-url` (str, default empty): template used when no shortcut matches; include `{q}` for the URL encoded query.

Override the location of `config.json` by setting the `GO_CONFIG_PATH` environment variable before starting the server. The admin Config page at `/admin/config` also edits and saves these values with validation.

## Using go

### Manage shortcuts

- Visit `http://127.0.0.1:5000/admin` to add, edit, delete, and tag shortcuts. List memberships are created automatically when you assign new slugs.
- File shortcuts must use `file://` URLs, require `allow-files` set to true, and the target directory must exist in `file-allow`.
- Keyword matching is case-insensitive; substring suggestions consider keyword, title, and URL fields.
- `http://127.0.0.1:5000/lists` surfaces lists and their member shortcuts.

Seed shortcuts from the command line with:

```bash
curl -X POST http://127.0.0.1:5000/api/links \
  -H "content-type: application/json" \
  -d '{"keyword":"cal","title":"My Calendar","url":"https://calendar.google.com"}'
```

### Import and export data

Use `python init_db.py` to ensure the database exists or to import a CSV export:

```bash
python init_db.py links.csv
# CSV columns: keyword,title,url,search_enabled,lists
```

Rows are matched by keyword or URL; newer entries overwrite existing shortcuts and URLs must be unique after import. The script also ensures the lists schema exists so the admin UI works immediately.

Export the current shortcuts at any time:

- Download `http://127.0.0.1:5000/export/shortcuts.csv`, or
- Click **Export CSV** from the admin UI.

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

All responses are JSON. There is no authentication; run the service on trusted networks only.

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
Dockerfile               # Multi-stage Windows container that runs the PyInstaller exe
docker/Dockerfile.linux  # Gunicorn-based Linux image that runs the source tree
docker/entrypoint.sh     # Linux entrypoint that patches config/db paths
docker/entrypoint.ps1    # Ensures config/db paths exist inside the container
docker-compose.yml       # Local stack wiring the Linux container + volume
```

## Development workflow

- Create pull requests with matching updates to `README.md`, `CHANGELOG.md`, and `todos.md` when behaviour changes.
- Run `python -m coverage run -m pytest` and `coverage report --fail-under=100` before you push; CI enforces full coverage.
- Keep lint tidy with `ruff check` and `ruff format`.
- When scripting edits, respect blueprint re-export patterns; see `agents.md` for safe-edit guidelines.

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

## Operational notes

- The app assumes localhost usage and exposes no authentication; keep it firewalled.
- Enabling `allow-files` without scoping `file-allow` may expose sensitive paths; configure both.
- The tray icon (via `pystray` and `pillow`) offers quick links to Home and Admin when those packages are installed.

## Roadmap

High-level planning lives in `todos.md`. Upcoming milestones focus on 1.0 documentation polish, 2.0 authentication and hardening, and longer-term platform support explorations.

## How to contribute

- Read this README plus `todos.md` to understand current priorities.
- Prefer focused commits with clear scope and updated docs.
- Automation or agent workflows should start with `agents.md` and reuse existing helpers when extending blueprints.

## License

MIT. See `LICENSE` for details.
