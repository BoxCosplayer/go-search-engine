#!/usr/bin/env python3
"""
Initialize the SQLite database and optionally import links from a CSV file.
Usage:
  python init_db.py                # creates data/links.db
  python init_db.py links.csv      # also imports CSV rows
CSV format:
  keyword,title,url
"""

import csv
import os
import sqlite3
import sys

# Use the same default DB location as the app
try:
    from backend.app.db import DB_PATH, ensure_lists_schema  # type: ignore
except Exception:
    # Fallback to repo-local data folder
    DB_PATH = os.environ.get(
        "GO_DB_PATH", os.path.join(os.path.dirname(__file__), "backend", "app", "data", "links.db")
    )

    def ensure_lists_schema(conn):
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
      title TEXT
    );
    """)
    conn.commit()


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
