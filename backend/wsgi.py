"""WSGI entrypoint for deployment.

Example usage (gunicorn):
    gunicorn backend.wsgi:application
"""

from .app import app as application

# Optional alias so both `application` and `app` work
app = application
