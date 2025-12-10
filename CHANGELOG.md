# Changelog

## [Major Versions Log](#major-versions-log)

## 1.1.8

- Trimmed down files slightly
- Added testing to verify versioning

## 1.1.7

- Added CI security gates (namely SAST and dependency enforcement)
- Applied the same gates to docker builds

## 1.1.6

- Fixed the bundled executable so it now creates all external files (config.json and links.db) in the users appdata folder
- Updated docs and all helper functions to default to the new location
- Removed ability to change where db lives
- Set debug defaults

## 1.1.5

- Updated the docker documentation

## 1.1.4

- Expanded the docker architecture
- Docker files now supports Linux Operating Systems

## 1.1.3

- Updated release to include the exe file
- EXE now bundles the Flask templates and loads them from the packaged resources so pages render successfully

## 1.1.2

- Creating a list via adding a new list to a link behaves identically to creating normal lists

## 1.1.1

- Deleting a list now also removes the automatically generated shortcut link

## 1.1.0

- Added a Windows Dockerfile and entrypoint script so the packaged EXE can run inside Docker
- Documented the container workflow and wired CI to build the image on every push

## 1.0.0

- Fully reworked documentation



## 0.5.2

- Added a workflow that builds and publishes a release on every push

## 0.5.1

- Handled conflicts by prioritising newer keyword entries
- Conflicts are detected by URLs and keywords

## 0.5.0

- Added Imports and Exports for shortcuts
- Added ability to extend current db with an import, rather than replace


## 0.4.2

- Added a per-shortcut search flag that enables `go !keyword {terms}` to proxy the site's OpenSearch provider with mock TLS connections.
- Persisted the flag in SQLite, surfaced it across the admin UI/API/index listings, and backfilled migration helpers.

## 0.4.1

- Removed support for multi-keyword searching
- Whitespace in setting keyword presents error

## 0.4.0

- Added OpenSearch description/suggestions endpoints and discovery tags
- Documented browser integration guidance in the README


## 0.3.3

- Added agents.md in project root
- Documented / highlighted agents.md in readme & added contribution section
- Published "todos.md"

## 0.3.2

- Modularised the admin init file, splitting endpoints across different files

## 0.3.1

- Enforced pytest coverage in CI/CD

## 0.3.0

- Added 100% pytest Coverage


## 0.2.4

- Added full CRUD access to the API

## 0.2.3

- Added ability to edit existing links from the admin UI
- Added `PUT /api/links/<keyword>` for API interaction

## 0.2.2

- Added admin UI to change and update the config
- Added "Major Verions Log" to the changelog
- Removed Config from repo, added template for documentation purposes

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



# Major Versions Log

- 1.1 - Publication & QoL updates
- **1.0** - Reworked documentation

- 0.5 - Final cleanup and small additional features
- 0.4 - Enhanced Search
- 0.3 - Project Modularisation & testing
- 0.2 - Config Overhaul + extra admin powers
- 0.1 - Initial Project Publication
- 0.0 - Private project development, for private use
