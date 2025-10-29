import os
import sqlite3
import sys

from flask import g


def _base_dir() -> str:
    """Return the base directory for app data.

    Uses the directory of the executable when running as a PyInstaller bundle,
    otherwise the directory of this module. This keeps the database and other
    runtime files colocated with the app.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(__file__)


BASE_DIR = _base_dir()

DB_PATH = os.environ.get("GO_DB_PATH", os.path.join(BASE_DIR, "data", "links.db"))


def get_db():
    """Get a request-scoped SQLite connection.

    - Creates the `data/` directory under BASE_DIR if needed.
    - Enables `PRAGMA foreign_keys = ON`.
    - Stores the connection in Flask's `g` so each request reuses a single
      connection.

    Returns:
        sqlite3.Connection: The open database connection.
    """
    if "db" not in g:
        os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exc):
    """Teardown handler: close the request-scoped DB connection if present."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Ensure the core `links` table exists.

    Creates the `links` table if missing and commits the change.
    """
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          keyword TEXT NOT NULL UNIQUE,
          url TEXT NOT NULL,
          title TEXT
        );
        """
    )
    db.commit()


def ensure_lists_schema(db):
    """Ensure list-related tables exist (`lists`, `link_lists`).

    Args:
        db: An open sqlite3.Connection to run DDL statements against.
    """
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS lists (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          slug TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          description TEXT
        );
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS link_lists (
          link_id INTEGER NOT NULL,
          list_id INTEGER NOT NULL,
          PRIMARY KEY (link_id, list_id),
          FOREIGN KEY (link_id) REFERENCES links(id) ON DELETE CASCADE,
          FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()


def init_app(app):
    """Register DB teardown and run one-time migration.

    Args:
        app: The Flask application instance.
    """
    migrate_old_db_if_present()
    app.teardown_appcontext(close_db)


def migrate_old_db_if_present():
    """Move an old root-level data/links.db into the new package data path.

    Old path: <project_root>/data/links.db
    New path: BASE_DIR/data/links.db
    """
    try:
        backend_dir = os.path.dirname(BASE_DIR)
        project_root = os.path.dirname(backend_dir)
        old_path = os.path.join(project_root, "data", "links.db")
        new_dir = os.path.join(BASE_DIR, "data")
        new_path = os.path.join(new_dir, "links.db")
        if os.path.exists(old_path) and not os.path.exists(new_path):
            os.makedirs(new_dir, exist_ok=True)
            os.replace(old_path, new_path)
    except Exception:
        # Non-fatal; continue without migration
        pass
