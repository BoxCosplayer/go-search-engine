"""Compatibility stub after restructuring.

- Running `python app.py` will execute the moved module's `__main__` block
  so tray/server behavior is unchanged.
- Importing from this module exposes the Flask `app` instance for tools
  that expect `app` at the project root.
"""

import runpy

# Expose `app` for importers if needed (e.g., old references)
try:
    from backend.app.main import app  # type: ignore
except Exception:  # pragma: no cover
    app = None  # lazy import at runtime via run_module

if __name__ == "__main__":
    runpy.run_module("backend.app.main", run_name="__main__")
