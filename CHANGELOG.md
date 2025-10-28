# Changelog

## [0.1.0] - 2025-10-28

Added
- Backend package structure: app moved to `backend/app/main.py` with `backend/wsgi.py` entrypoint.
- Blueprints: API (`/api`), Admin (`/admin`), and Lists (`/lists`).
- Jinja templates extracted to `backend/app/templates/` (no more inline HTML).
- Database migration: automatically moves old `data/links.db` to `backend/app/data/links.db` on startup.
- Lint/format tooling via Ruff with `.ruff.toml`.
- PyInstaller packaging support: `go-server.spec` now bundles templates.
- Version exposed as `backend.app.__version__ = "0.1.0"`.

Changed
- Consolidated dependencies into a single `requirements.txt` (includes Ruff).
- Updated README with new layout, run, lint, and packaging instructions.
- Expanded `.gitignore` to cover common Python, build, and environment artifacts.
- Switched to `python-slugify` and updated imports.

Fixed
- Index route now ensures lists schema exists to avoid missing-table errors.

Removed
- Old inline HTML constants and duplicate DB/helper functions from `main.py`.

Migration notes
- If you previously used the root `data/links.db`, it will be migrated automatically to `backend/app/data/links.db` on first run.
