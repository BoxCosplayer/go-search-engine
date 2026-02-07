# AGENTS.md

## Purpose
This file is the current agent operating guide for `go-search-engine`.
It now includes a full audit baseline from **February 7, 2026** and replaces older assumptions that no longer match the codebase.

## Current Reality (Verified)
- Stack: Python 3.11+ (CI), Flask, SQLite, Waitress, PyInstaller.
- Main app wiring: `backend/app/main.py`.
- Blueprints:
  - `admin` in `backend/app/admin/__init__.py`
  - `api` in `backend/app/api/__init__.py`
  - `lists` in `backend/app/lists/__init__.py`
- Admin modules are now: `auth.py`, `home.py`, `config_routes.py`, `links.py`, `lists.py`, `users.py`.
- Coverage gate in CI is still 90%, but current suite is much higher.

## Incorrect Assumptions From Prior Guide
- Old assumption: admin blueprint concerns are only `home/config_routes/links/lists`.
  - Actual: admin auth and user lifecycle are first-class (`backend/app/admin/auth.py`, `backend/app/admin/users.py`).
- Old assumption: this is mainly a no-auth admin UI.
  - Actual behavior is mixed and requires careful review. README still contains contradictory messaging.
- Old guide did not call out critical security drift around API auth and CSRF.

## Audit Baseline (2026-02-07)
Commands run locally:
- `.\.venv\Scripts\python.exe -m coverage run -m pytest`
- `.\.venv\Scripts\python.exe -m coverage report --fail-under=90`
- `.\.venv\Scripts\ruff.exe check .`
- `.\.venv\Scripts\ruff.exe format --check .`
- `.\.venv\Scripts\bandit.exe -r backend app.py init_db.py`
- `.\.venv\Scripts\pip-audit.exe --strict`

Observed results:
- Tests: **189 passed**
- Coverage: **99% total**
- Ruff: clean
- Bandit: no findings
- pip-audit: no known vulnerabilities

Important caveat:
- `backend/app/search_cache.py` has only **77%** coverage despite high aggregate coverage.

## Security Findings (Prioritized)

### P0 - API auth bypass when admin auth is enabled
Evidence:
- API blueprint is registered directly with no auth wrapper: `backend/app/main.py:206`
- Admin blueprint explicitly enforces auth: `backend/app/admin/__init__.py:10-12`
- API routes mutate data without auth guard (for example):
  - `backend/app/api/__init__.py:329`
  - `backend/app/api/__init__.py:461`
  - `backend/app/api/__init__.py:477`
  - `backend/app/api/__init__.py:528`

Risk:
- If service is reachable off-host, unauthenticated callers can create/update/delete links and lists even with admin auth enabled.

### P0 - No CSRF protection on state-changing forms
Evidence:
- POST admin/list forms exist with no CSRF token mechanism:
  - `backend/app/templates/admin/index.html:519`
  - `backend/app/templates/admin/index.html:527`
  - `backend/app/templates/admin/index.html:543`
  - `backend/app/templates/admin/index.html:559`
  - `backend/app/templates/admin/users.html:243`
  - `backend/app/templates/lists/index.html:121`
  - `backend/app/templates/lists/view.html:142`
- No CSRF framework references found in app code.

Risk:
- Browser-authenticated admins can be forced to submit destructive POSTs from malicious pages.

### P1 - First-credential bootstrap can be remotely claimed
Evidence:
- Empty `admin_users` table + provided Basic auth creates first admin user:
  - `backend/app/admin/auth.py:75`
  - `backend/app/admin/auth.py:95-99`

Risk:
- On first deployment, any reachable client that sends credentials first can become admin.

### P1 - Admin link add/update accepts arbitrary URL schemes
Evidence:
- Admin form handlers only check non-empty URL, not scheme:
  - `backend/app/admin/links.py:17-18`
  - `backend/app/admin/links.py:65-67`
- Redirect helper will redirect unknown schemes by default:
  - `backend/app/main.py:216-218`
  - `backend/app/main.py:255`

Risk:
- Malicious or unsafe schemes can be stored and executed via user click flow.

### P2 - Host header trust in generated URLs
Evidence:
- List URL generation uses `request.host_url` directly:
  - `backend/app/admin/lists.py:26`
  - `backend/app/admin/lists.py:62`
  - `backend/app/api/__init__.py:508`
  - `backend/app/api/__init__.py:579`
- OpenSearch description also uses host-derived URL:
  - `backend/app/api/__init__.py:733`

Risk:
- Incorrect absolute URL generation or poisoning in proxied deployments without strict host validation.

## Maintenance Findings

### Config reload semantics are inconsistent
Evidence:
- Module constants captured at import:
  - `backend/app/main.py:83`
  - `backend/app/main.py:84`
- Runtime config is mutable in admin:
  - `backend/app/admin/config_routes.py:96`

Impact:
- Saving config does not reliably update all runtime behavior until restart (for example fallback URL and file-access flag paths depending on constant usage).

### API module is too large and multi-purpose
Evidence:
- `backend/app/api/__init__.py` handles route registration, CSV import/export, suggestion engine, OpenSearch endpoints, and logging concerns in one file.

Impact:
- Harder code review, riskier edits, less isolated tests, more accidental regressions.

### Duplicate config loading concepts
Evidence:
- `backend/app/utils.py:333` defines canonical config load.
- `backend/app/main.py:162` has another `load_config()` that is separate and easy to drift.

Impact:
- Confusing source of truth and higher long-term drift risk.

### Broad exception handling hides causes
Examples:
- `backend/app/admin/links.py` wraps broad exceptions for duplicate behavior.
- `backend/app/admin/lists.py:77` suppresses all exceptions when creating list shortcut links.

Impact:
- Operational debugging and root-cause analysis becomes slower.

## DX Findings
- No typed static analysis gate (mypy/pyright) despite complex cross-module state.
- Runtime and dev/security dependencies are combined in a single `requirements.txt`.
- No fast local task runner (`make`, `just`, `tox`, or `nox`) for standard commands.
- No pre-commit hook baseline to enforce local consistency before push.
- README contains conflicting auth statements and should be normalized.

## Testing and Validation Gaps
- Missing direct tests for API auth enforcement behavior under `admin_auth_enabled`.
- Missing CSRF tests (expected to fail until CSRF is implemented).
- Missing focused tests for `backend/app/search_cache.py` branch behavior and eviction.
- Missing host-header/absolute URL generation tests.
- Missing regression tests for config save behavior vs runtime constants.
- Missing integration tests for docker entrypoints and environment-driven config patching.

## Required Workflow for Future Agents
1. Read `CHANGELOG.md`, `README.md`, and this file before edits.
2. For any auth/routing change, inspect:
   - `backend/app/main.py`
   - `backend/app/admin/__init__.py`
   - `backend/app/admin/auth.py`
   - `backend/app/api/__init__.py`
3. If config keys or semantics change, update:
   - `config-template.txt`
   - `README.md`
   - `test/conftest.py`
4. If release behavior changes, update:
   - `backend/app/__init__.py` version
   - `CHANGELOG.md`
   - `go-server.spec` packaging notes if relevant
5. Always rerun:
   - `.\.venv\Scripts\python.exe -m coverage run -m pytest`
   - `.\.venv\Scripts\python.exe -m coverage report --fail-under=90`
   - `.\.venv\Scripts\ruff.exe check .`
   - `.\.venv\Scripts\ruff.exe format --check .`
   - `.\.venv\Scripts\bandit.exe -r backend app.py init_db.py`
   - `.\.venv\Scripts\pip-audit.exe --strict`

## Immediate Remediation Queue
1. [Done] Enforce API authentication parity with admin auth (P0).
2. [Done] Add CSRF protection to all state-changing browser forms (P0).
3. [Done] Replace bootstrap-first-login with controlled bootstrap token/flow (P1).
4. [Done] Restrict allowed redirect URL schemes and validate admin URL input (P1).
5. [Open] Refactor `backend/app/api/__init__.py` into smaller modules and add targeted tests.
6. [Open] Add dedicated `search_cache` unit tests and close uncovered lines.
