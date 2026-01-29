#!/usr/bin/env python3
"""
Initialize the SQLite database and optionally import links from a CSV file.
Usage:
  python init_db.py                # creates the default user-data links.db
  python init_db.py links.csv      # also imports CSV rows
CSV format:
  keyword,title,url
"""

import csv
import os
import sqlite3
import sys
from pathlib import Path


def _default_db_path() -> str:
    """Return the platform-specific default DB location."""

    name = "go-search-engine"
    if sys.platform.startswith("win"):
        root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if root:
            return str(Path(root) / name / "links.db")
        return str(Path.home() / "AppData" / "Roaming" / name / "links.db")
    if sys.platform == "darwin":
        return str(Path.home() / "Library" / "Application Support" / name / "links.db")
    return str(Path.home() / ".local" / "share" / name / "links.db")


# Default to repo-local data folder; override if backend.app.db is importable
DB_PATH = os.environ.get("GO_DB_PATH", _default_db_path())


def _fallback_ensure_lists_schema(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS lists (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      slug TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL,
      description TEXT
    );
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS link_lists (
      link_id INTEGER NOT NULL,
      list_id INTEGER NOT NULL,
      PRIMARY KEY (link_id, list_id),
      FOREIGN KEY (link_id) REFERENCES links(id) ON DELETE CASCADE,
      FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE CASCADE
    );
    """)
    conn.commit()


def _fallback_ensure_search_flag_column(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(links)")}
    if "search_enabled" not in cols:
        conn.execute("ALTER TABLE links ADD COLUMN search_enabled INTEGER NOT NULL DEFAULT 0")
        conn.commit()


def _fallback_ensure_admin_users_schema(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS admin_users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      is_active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()


def _fallback_ensure_search_fts(conn):
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS links_fts USING fts5(
              keyword,
              title,
              content='links',
              content_rowid='id',
              tokenize='trigram'
            );
            """
        )
    except sqlite3.OperationalError:
        return False
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS links_fts_ai AFTER INSERT ON links BEGIN
          INSERT INTO links_fts(rowid, keyword, title) VALUES (new.id, new.keyword, new.title);
        END;
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS links_fts_ad AFTER DELETE ON links BEGIN
          INSERT INTO links_fts(links_fts, rowid, keyword, title)
          VALUES('delete', old.id, old.keyword, old.title);
        END;
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS links_fts_au AFTER UPDATE ON links BEGIN
          INSERT INTO links_fts(links_fts, rowid, keyword, title)
          VALUES('delete', old.id, old.keyword, old.title);
          INSERT INTO links_fts(rowid, keyword, title) VALUES (new.id, new.keyword, new.title);
        END;
        """
    )
    conn.execute("INSERT INTO links_fts(links_fts) VALUES('rebuild')")
    conn.commit()
    return True


ensure_lists_schema = _fallback_ensure_lists_schema
ensure_search_flag_column = _fallback_ensure_search_flag_column
ensure_admin_users_schema = _fallback_ensure_admin_users_schema
ensure_search_fts = _fallback_ensure_search_fts


try:
    import backend.app.db as _db
except ImportError as exc:  # pragma: no cover - optional fallback path
    print(f"Using fallback DB helpers: {exc}", file=sys.stderr)  # pragma: no cover
else:
    DB_PATH = _db.DB_PATH
    ensure_lists_schema = _db.ensure_lists_schema
    ensure_search_flag_column = _db.ensure_search_flag_column
    ensure_admin_users_schema = _db.ensure_admin_users_schema
    ensure_search_fts = _db.ensure_search_fts


def ensure_schema(conn):
    """Create the core `links` table if it does not exist.

    Args:
        conn (sqlite3.Connection): Open connection to the database file.

    Side effects:
        Executes DDL and commits the transaction.
    """
    conn.execute("""
    CREATE TABLE IF NOT EXISTS links (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      keyword TEXT NOT NULL UNIQUE,
      url TEXT NOT NULL,
      title TEXT,
      search_enabled INTEGER NOT NULL DEFAULT 0
    );
    """)
    conn.commit()
    ensure_search_flag_column(conn)


def import_csv(conn, path):
    """Import links from a CSV file into the `links` table.

    The CSV is expected to have a header row with columns:
    `keyword,title,url`.

    Args:
        conn (sqlite3.Connection): Database connection to write into.
        path (str): Path to the CSV file on disk.
    """
    with open(path, newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            kw = (row.get("keyword") or "").strip()
            url = (row.get("url") or "").strip()
            title = (row.get("title") or "").strip() or None
            if not kw or not url:
                print(f"Skipping row with missing keyword/url: {row}")
                continue
            try:
                conn.execute("INSERT INTO links(keyword, url, title) VALUES (?, ?, ?)", (kw, url, title))
                print(f"Added: {kw} -> {url}")
            except sqlite3.IntegrityError:
                print(f"Skipping existing keyword: {kw}")
    conn.commit()


def main():
    """Initialize the database file and optionally import a CSV.

    Behavior:
      - Ensures the database directory exists.
      - Creates core schema (`links`) and list-related schema.
      - If a CSV path is provided as the first CLI argument, imports rows.
      - Otherwise, prints the initialized DB path.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        ensure_schema(conn)
        # Also ensure lists schema so admin/lists UIs work out-of-the-box
        ensure_lists_schema(conn)
        ensure_search_flag_column(conn)
        ensure_admin_users_schema(conn)
        ensure_search_fts(conn)

        if len(sys.argv) >= 2:
            csv_path = sys.argv[1]
            if not os.path.exists(csv_path):
                print(f"CSV not found: {csv_path}")
                sys.exit(1)
            import_csv(conn, csv_path)
        else:
            print("Initialized DB at", DB_PATH)


if __name__ == "__main__":  # pragma: no cover
    main()
