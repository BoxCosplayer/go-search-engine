import sqlite3
from pathlib import Path

from backend.app.db import close_db, ensure_lists_schema, ensure_search_flag_column, get_db, init_db


def test_get_db_reuses_connection(app_ctx):
    conn1 = get_db()
    conn2 = get_db()
    assert conn1 is conn2
    close_db(None)


def test_get_db_handles_relative_path(app_ctx, monkeypatch, tmp_path):
    from backend.app import db as db_mod

    close_db(None)
    relative = Path("relative") / "test.sqlite"
    monkeypatch.setattr(db_mod, "DB_PATH", str(relative), raising=False)
    monkeypatch.setattr(db_mod, "BASE_DIR", str(tmp_path), raising=False)
    conn = get_db()
    assert (tmp_path / relative).exists()
    conn.execute("SELECT 1")  # sanity check
    close_db(None)


def test_init_db_creates_links_table(app_ctx):
    init_db()
    conn = get_db()
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='links'").fetchone()
    assert row["name"] == "links"
    cols = {info["name"] for info in conn.execute("PRAGMA table_info(links)").fetchall()}
    assert "search_enabled" in cols
    close_db(None)


def test_ensure_search_flag_column_adds_missing_column(tmp_path):
    db_file = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db_file)
    conn.execute(
        """
        CREATE TABLE links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          keyword TEXT NOT NULL UNIQUE,
          url TEXT NOT NULL,
          title TEXT
        );
        """
    )
    conn.commit()
    ensure_search_flag_column(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(links)")}
    assert "search_enabled" in columns
    conn.close()


def test_ensure_lists_schema_creates_tables(app_ctx):
    conn = get_db()
    ensure_lists_schema(conn)
    names = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('lists','link_lists')"
        ).fetchall()
    }
    assert names == {"lists", "link_lists"}
    close_db(None)


def test_db_base_dir_handles_frozen(monkeypatch, tmp_path):
    from backend.app import db as db_mod

    monkeypatch.setattr(db_mod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(db_mod.sys, "executable", str(tmp_path / "app.exe"), raising=False)
    assert db_mod._base_dir() == str(tmp_path)
