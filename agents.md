# Effective Agents Guide

This project may rely on automation or AI-assisted agents to keep the codebase consistent and fully covered. Use this document as a guide when driving those agents.

## Project Snapshot
- Stack: Python (3.11+ CI, 3.13 local), Flask, SQLite, PyInstaller.
- Layout: `backend/app` holds blueprints (`admin`, `api`, `lists`) and shared modules (`main.py`, `db.py`, `utils.py`).
- Admin blueprint is split by concern (`home.py`, `config_routes.py`, `links.py`, `lists.py`) with re-exports in `backend/app/admin/__init__.py`.
- Tests live under `test/` and must keep `coverage run -m pytest` at 100%.

## Agent Workflow
1. **Sync context first**
   - Inspect open PR notes, `CHANGELOG.md`, and `todos.md`.
   - Read the relevant module before editing; many helpers are re-exported for compatibility.
2. **Plan concretely**
   - Break work into small, verifiable steps.
   - Note dependencies (e.g., schema helpers in `backend/app/db.py`).
3. **Edit safely**
   - Prefer targeted patches (`apply_patch` or equivalent) and keep imports sorted.
   - Maintain ASCII unless the surrounding file already uses Unicode.
   - For admin routes, update the respective module and consider the re-export list in `backend/app/admin/__init__.py`.
4. **Keep docs in sync**
   - Update README snippets, CHANGELOG entries, and API docs when behavior changes.
   - Surface new CLI flags or environment expectations here for future agents.

## Testing & Quality Gates
- Always run `.\.venv\Scripts\python.exe -m coverage run -m pytest` (or `python -m coverage run -m pytest` on Linux) after code changes.
- Follow up with `coverage report --fail-under=100`. CI enforces 100% coverage via `.github/workflows/ci.yml`.
- Ruff is configured via `.ruff.toml`; run `ruff check`/`ruff format` after touching Python code.

## Common Scenarios
- **Adding admin endpoints**: place handlers in a dedicated module, import it from `backend/app/admin/__init__.py`, and expose the callable through the re-export list.
- **Modifying configuration helpers**: adjust `backend/app/utils.py`, ensure fixtures in `test/conftest.py` still patch the right attributes, and extend tests to exercise new branches.
- **Extending the API**: update `backend/app/api/__init__.py`, add route tests in `test/test_api.py`, and document payloads in README.
- **Database changes**: revise schema migrations in `init_db.py`, adjust `ensure_lists_schema` or related helpers, and cover the change with both unit tests and integration tests.

## Reporting & Notes
- Record significant decisions in `CHANGELOG.md`.
- Use `todos.md` for longer-running follow-ups; keep entries actionable.
- Log coverage adjustments or temporary skips directly in commit/PR descriptions.

Sticking to this checklist keeps agent-driven changes predictable, testable, and aligned with the repository’s guarantees. Feel free to expand this guide as new automation patterns emerge.
