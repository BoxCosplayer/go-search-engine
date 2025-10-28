"""App package: exposes the Flask `app` instance.

Importing `backend.app` gives you the `app` object from
`backend.app.main` so WSGI servers and tools can reference
`backend.app:app`.
"""

__all__ = ["app", "__version__"]
__version__ = "0.1.0"

from .main import app  # noqa: F401
