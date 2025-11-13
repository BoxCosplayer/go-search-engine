import os
import sqlite3
import sys
from pathlib import Path

from flask import g

from .utils import get_db_path


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

DB_PATH = str(get_db_path())


def get_db():
    """Get a request-scoped SQLite connection.

    - Enables `PRAGMA foreign_keys = ON`.
    - Stores the connection in Flask's `g` so each request reuses a single
      connection.

    Returns:
        sqlite3.Connection: The open database connection.
    """
    if "db" not in g:
        db_file = Path(DB_PATH)
        if not db_file.is_absolute():
            db_file = Path(BASE_DIR) / db_file
        db_file.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(str(db_file))
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
          title TEXT,
          search_enabled INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    db.commit()
    ensure_search_flag_column(db)


def ensure_search_flag_column(db):
    """Ensure the `search_enabled` column exists on the links table."""
    cols = set()
    for row in db.execute("PRAGMA table_info(links)"):
        if hasattr(row, "keys"):
            cols.add(row["name"])
        else:  # pragma: no cover -- fallback when row_factory not set
            cols.add(row[1])
    if "search_enabled" not in cols:
        db.execute("ALTER TABLE links ADD COLUMN search_enabled INTEGER NOT NULL DEFAULT 0")
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
    app.teardown_appcontext(close_db)
