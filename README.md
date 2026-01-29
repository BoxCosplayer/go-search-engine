# go -- local shortcuts server

## Local keyword redirects with a lightweight admin UI and API

Run a local Flask server that lets you type `go <keyword>` (or `go !keyword [search-term]`) in your browser address bar and jump to saved destinations. It ships with a no-auth admin UI, a JSON API, optional search bangs via OpenSearch, and optional file launches guarded by a whitelist. It is currently intended for localhost usage and can run from source, Docker, or a bundled EXE.

## Demonstration

Youtube demonstration currently in the works.

## Quick install

1. Download the latest `go-server.exe` from the Releases page.
2. Run it from an empty folder. Runtime files live under `%APPDATA%\go-search-engine` (Windows) or `~/.local/share/go-search-engine` (Linux), including `config.json`, `links.db`, and `go-search-engine.log`.
3. Edit `config.json` (host, port, debug, allow-files, file-allow, fallback-url, admin-auth-enabled, log-level, log-file) and restart the binary.
4. Open `http://127.0.0.1:5000/admin` to add shortcuts and lists.
   - When the database starts empty, the app seeds `home`, `lists`, and `admin` shortcuts pointing at the configured host/port.

Finally, add it to your search engine list with the keyword `go`, and go!

```
name: go
url: http://[ip]:[port]/go?q=%s
keyword: go
```

Set `GO_DB_PATH` before launch if you need to relocate `links.db`.
Use `GO_CONFIG_PATH` to override the config location.
Set `GO_LOG_PATH` to move the log file, or `GO_LOG_LEVEL` to change verbosity.

## Advanced install for Docker

### Linux containers (Gunicorn)

1. Pull `ghcr.io/boxcosplayer/go-server:latest` or build locally:
   ```bash
   docker build -f docker/Dockerfile.linux -t go-server:linux .
   ```
2. Run it with a volume mounted at `/data`:
   ```bash
   docker run --rm -p 5000:5000 -v go-data:/data ghcr.io/boxcosplayer/go-server:latest
   ```
3. The entrypoint copies `config-template.txt` into `/data/config.json` on first start, sets `GO_DB_PATH` (default `/data/links.db`), and boots Gunicorn via `backend.wsgi:application`.

Compose is available for local repeatable setups:

```bash
docker compose up --build
```

Common Linux container variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GO_CONFIG_PATH` | `/data/config.json` | Location of the runtime config file. |
| `GO_DB_PATH` | `/data/links.db` | SQLite destination the server uses. |
| `GO_LOG_PATH` | `/data/go-search-engine.log` | Location of the log file. |
| `GO_LOG_LEVEL` | `INFO` | Logging verbosity (DEBUG, INFO, WARNING, ERROR, CRITICAL). |
| `GO_HOST` | `127.0.0.1` | Interface the server binds to inside the container. |
| `GO_PORT` | `5000` | In-container TCP port; match the host mapping when overriding. |
| `GO_GUNICORN_WORKERS` | `2` | Worker processes for Gunicorn. |
| `GO_GUNICORN_TIMEOUT` | `60` | Request timeout for Gunicorn, in seconds. |
| `GO_GUNICORN_EXTRA_ARGS` | *(empty)* | Extra CLI switches appended to the default Gunicorn command. |

### Windows containers (EXE)

1. Switch Docker Desktop to Windows container mode.
2. Build the image:
   ```powershell
   docker build -t go-server:exe .
   ```
3. Run it with data stored under `C:\data`:
   ```powershell
   docker run --rm -p 5000:5000 -v go-data:C:\data go-server:exe
   ```

Common Windows container variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GO_CONFIG_PATH` | `C:\data\config.json` | Location of the runtime config file. |
| `GO_DB_PATH` | `C:\data\links.db` | SQLite destination the server uses. |
| `GO_LOG_PATH` | `C:\data\go-search-engine.log` | Location of the log file. |
| `GO_LOG_LEVEL` | `INFO` | Logging verbosity (DEBUG, INFO, WARNING, ERROR, CRITICAL). |
| `GO_HOST` | `127.0.0.1` | Interface the server binds to inside the container. |
| `GO_PORT` | `5000` | In-container TCP port; match the host mapping when overriding. |

## Run from Source

Python 3.11+ is required (CI runs 3.11; local development uses 3.13).

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m backend
```

The dev server uses `config.json` for host and port, and stores data/logs in the user data directory unless `GO_DB_PATH` or `GO_LOG_PATH` is set. Use `GO_CONFIG_PATH` to point at a different config file.

When `admin-auth-enabled` is true, `/admin` requires HTTP Basic Auth. If no admin users exist yet, the first successful Basic Auth attempt will create the initial user. Manage additional users at `http://127.0.0.1:5000/admin/users`.

## How does this work?

- `backend/app/main.py` builds the Flask app, loads config via `backend/app/utils.py`, and wires the `admin`, `api`, and `lists` blueprints.
- Admin routes live in `backend/app/admin/home.py`, `config_routes.py`, `links.py`, and `lists.py`, and are re-exported from `backend/app/admin/__init__.py`.
- `backend/app/db.py` owns SQLite connections and schema helpers; `init_db.py` can seed or import CSV data and ensures the lists schema.
- `backend/wsgi.py` is the production entry point, `app.py` is a compatibility shim, and `go-server.spec` bundles templates for the EXE.
- Request flow is simple: `/go` looks up the keyword in SQLite and redirects (or uses the fallback URL), while `/admin` and `/api` mutate the same database.

## Want to contribute?

- Read `todos.md`
- Launch an issue via GitHub GUI
- Create a branch & file a PR
- Ensure you run Tests/Linters before you commit
- Update Changelog and versioning if applicable (CHANGELOG.md, backend\app\__init__.py)

Recommended Test / Linting suite for CI

```bash
python -m coverage run -m pytest            # Alternatively: .\.venv\Scripts\python.exe -m coverage run -m pytest
coverage report --fail-under=90
ruff check backend
ruff format backend
bandit -r backend app.py init_db.py
pip-audit --strict
```

Alternatively - shoot me an email at rajveer@sandhuhome.uk

Thanks!
