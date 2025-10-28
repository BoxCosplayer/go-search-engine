Changelog

## 0.1.1
- Fixed issue where templates wouldnt be targeted correctly

## 0.1.0

- New backend package layout; app at `backend/app/main.py` and WSGI at `backend/wsgi.py`.
- Blueprints: API (`/api`), Admin (`/admin`), Lists (`/lists`).
- Templates moved to `backend/app/templates/` (no more inline HTML).
- DB lives at `backend/app/data/links.db` with automatic migration from `data/links.db`.
- Ruff lint/format via `.ruff.toml`; CI workflow for Ruff.
- PyInstaller spec bundles templates for the exe.
- Switched to `python-slugify` for slug generation.
- Minor fixes and cleanup (schema init, duplicate helpers removed).
