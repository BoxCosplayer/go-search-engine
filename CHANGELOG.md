# Changelog

## 0.2.1

- Bugfix where empty directory allowed for all files to be run
- Ruff format

## 0.2.0

- Merged all config variables into references for config.json
- Added new configurables:
    - "file_allow" for whitelisitng filepaths where files cna be opened
    - optional debug mode for development purposes
    - configurable fallback_url instead of just using google

## 0.1.4

- Fixed slugify / python-slugify conflicts for lists
- Added docstrings for all functions 

## 0.1.3

- Fixed ruff config
- Ruff formatting

## 0.1.2

- Fixed redirects
- Fixed delimeter display bug
- Added further usage instructions to readme.md
- Removed "debug" mode and port options in config.json

## 0.1.1

- Fixed issue where html templates wouldnt be targeted correctly

## 0.1.0

- New backend package layout; app at `backend/app/main.py` and WSGI at `backend/wsgi.py`.
- Blueprints: API (`/api`), Admin (`/admin`), Lists (`/lists`).
- Templates moved to `backend/app/templates/` (no more inline HTML).
- DB lives at `backend/app/data/links.db` with automatic migration from `data/links.db` (for older versions of the app).
- Ruff lint/format via `.ruff.toml`; CI workflow for Ruff.
- PyInstaller spec bundles templates for the exe.
- Switched to `python-slugify` for slug generation.
- Minor fixes and cleanup (schema init, duplicate helpers removed).
