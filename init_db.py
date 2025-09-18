#!/usr/bin/env python3
"""
Initialize the SQLite database and optionally import links from a CSV file.
Usage:
  python init_db.py                # creates data/links.db
  python init_db.py links.csv      # also imports CSV rows
CSV format:
  keyword,title,url
"""
import csv, os, sqlite3, sys

DB_PATH = os.environ.get("GO_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "links.db"))

def ensure_schema(conn):
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
    os.makedirs(os.path.join(os.path.dirname(__file__), "data"), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        ensure_schema(conn)

        if len(sys.argv) >= 2:
            csv_path = sys.argv[1]
            if not os.path.exists(csv_path):
                print(f"CSV not found: {csv_path}")
                sys.exit(1)
            import_csv(conn, csv_path)
        else:
            print("Initialized DB at", DB_PATH)

if __name__ == "__main__":
    main()
