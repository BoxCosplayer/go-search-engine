import os
import sqlite3
import sys

from flask import g


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(__file__)


BASE_DIR = _base_dir()

DB_PATH = os.environ.get("GO_DB_PATH", os.path.join(BASE_DIR, "data", "links.db"))


def get_db():
    if "db" not in g:
        os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
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
