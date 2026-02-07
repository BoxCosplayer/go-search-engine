import os
import sqlite3
import sys
from pathlib import Path

from flask import g

from .utils import config, get_db_path


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


def _resolve_db_path() -> Path:
    db_file = Path(DB_PATH)
    if not db_file.is_absolute():
        db_file = Path(BASE_DIR) / db_file
    return db_file


def _apply_sqlite_pragmas(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA synchronous = NORMAL")
    db.execute("PRAGMA temp_store = MEMORY")
    db.execute("PRAGMA cache_size = -20000")
    db.execute("PRAGMA busy_timeout = 5000")


def _build_seed_base_url(host: str, port: int) -> str:
    host = (host or "127.0.0.1").strip()
    base = host.rstrip("/") if host.startswith(("http://", "https://")) else f"http://{host}"
    host_part = base.split("://", 1)[-1]
    if ":" not in host_part:
        base = f"{base}:{port}"
    return base


def _seed_links_payload(base_url: str) -> list[tuple[str, str, str]]:
    base = base_url.rstrip("/")
    return [
        ("home", base, "Home"),
        ("lists", f"{base}/lists", "Lists"),
        ("admin", f"{base}/admin", "Admin"),
    ]


def ensure_links_schema(db):
    """Ensure the core `links` table exists and search flag column is present."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          keyword TEXT NOT NULL UNIQUE COLLATE NOCASE,
          url TEXT NOT NULL,
          title TEXT,
          search_enabled INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    db.commit()
    ensure_search_flag_column(db)
    ensure_opensearch_columns(db)


def ensure_seed_links(db, base_url: str | None = None) -> bool:
    """Seed default shortcuts when no links exist.

    Returns True when seeds are inserted; False when the table already had data.
    """
    existing = db.execute("SELECT 1 FROM links LIMIT 1").fetchone()
    if existing:
        return False
    if base_url is None:
        base_url = _build_seed_base_url(
            getattr(config, "host", "127.0.0.1"),
            int(getattr(config, "port", 5000)),
        )
    payload = _seed_links_payload(base_url)
    db.executemany(
        "INSERT OR IGNORE INTO links(keyword, url, title) VALUES (?, ?, ?)",
        payload,
    )
    db.commit()
    return True


def get_db():
    """Get a request-scoped SQLite connection.

    - Enables `PRAGMA foreign_keys = ON`.
    - Applies connection pragmas for performance.
    - Stores the connection in Flask's `g` so each request reuses a single
      connection.

    Returns:
        sqlite3.Connection: The open database connection.
    """
    if "db" not in g:
        db_file = _resolve_db_path()
        db_file.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(str(db_file))
        g.db.row_factory = sqlite3.Row
        _apply_sqlite_pragmas(g.db)
    return g.db


def close_db(exc):
    """Teardown handler: close the request-scoped DB connection if present."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Ensure the core schema exists and seed defaults."""
    db = get_db()
    ensure_links_schema(db)
    ensure_lists_schema(db)
    ensure_admin_users_schema(db)
    ensure_indexes(db)
    ensure_search_fts(db)
    ensure_seed_links(db)


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


def ensure_opensearch_columns(db):
    """Ensure OpenSearch metadata columns exist on the links table."""
    cols = set()
    for row in db.execute("PRAGMA table_info(links)"):
        if hasattr(row, "keys"):
            cols.add(row["name"])
        else:  # pragma: no cover -- fallback when row_factory not set
            cols.add(row[1])
    updated = False
    if "opensearch_doc_url" not in cols:
        db.execute("ALTER TABLE links ADD COLUMN opensearch_doc_url TEXT")
        updated = True
    if "opensearch_template" not in cols:
        db.execute("ALTER TABLE links ADD COLUMN opensearch_template TEXT")
        updated = True
    if updated:
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
          slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
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


def ensure_admin_users_schema(db):
    """Ensure admin user tables exist (`admin_users`)."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL UNIQUE COLLATE NOCASE,
          password_hash TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    db.commit()


def ensure_indexes(db):
    """Ensure lookup and ordering indexes exist."""
    db.execute("CREATE INDEX IF NOT EXISTS idx_links_keyword_nocase ON links(keyword COLLATE NOCASE)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_links_url_nocase ON links(url COLLATE NOCASE)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_lists_slug_nocase ON lists(slug COLLATE NOCASE)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_lists_name_nocase ON lists(name COLLATE NOCASE)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_link_lists_list_id ON link_lists(list_id)")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_users_username_nocase ON admin_users(username COLLATE NOCASE)"
    )
    db.commit()


def _has_trigger(db: sqlite3.Connection, name: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=? LIMIT 1",
            (name,),
        ).fetchone()
        is not None
    )


def ensure_search_fts(db: sqlite3.Connection) -> bool:
    """Ensure the FTS5 trigram index for substring suggestions exists."""
    existing = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='links_fts' LIMIT 1").fetchone()
    created = False
    if not existing:
        try:
            db.execute(
                """
                CREATE VIRTUAL TABLE links_fts USING fts5(
                  keyword,
                  title,
                  content='links',
                  content_rowid='id',
                  tokenize='trigram'
                );
                """
            )
            created = True
        except sqlite3.OperationalError as exc:
            raise RuntimeError(
                "SQLite FTS5 with the trigram tokenizer is required for search suggestions."
            ) from exc

    triggers_missing = created or not all(
        _has_trigger(db, name) for name in ("links_fts_ai", "links_fts_ad", "links_fts_au")
    )

    try:
        db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS links_fts_ai AFTER INSERT ON links BEGIN
              INSERT INTO links_fts(rowid, keyword, title) VALUES (new.id, new.keyword, new.title);
            END;
            """
        )
        db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS links_fts_ad AFTER DELETE ON links BEGIN
              INSERT INTO links_fts(links_fts, rowid, keyword, title)
              VALUES('delete', old.id, old.keyword, old.title);
            END;
            """
        )
        db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS links_fts_au AFTER UPDATE ON links BEGIN
              INSERT INTO links_fts(links_fts, rowid, keyword, title)
              VALUES('delete', old.id, old.keyword, old.title);
              INSERT INTO links_fts(rowid, keyword, title) VALUES (new.id, new.keyword, new.title);
            END;
            """
        )

        if triggers_missing:
            db.execute("INSERT INTO links_fts(links_fts) VALUES('rebuild')")
        db.commit()
        return True
    except sqlite3.OperationalError as exc:
        raise RuntimeError("Failed to configure SQLite FTS5 triggers.") from exc


def init_app(app):
    """Register DB teardown and run one-time migration.

    Args:
        app: The Flask application instance.
    """
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
