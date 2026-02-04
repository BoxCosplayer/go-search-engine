import sqlite3
from pathlib import Path

from backend.app.db import (
    close_db,
    ensure_admin_users_schema,
    ensure_links_schema,
    ensure_lists_schema,
    ensure_opensearch_columns,
    ensure_search_flag_column,
    ensure_seed_links,
    get_db,
    init_db,
)


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
    assert "opensearch_doc_url" in cols
    assert "opensearch_template" in cols
    close_db(None)


def test_seed_links_inserted_when_empty(app_ctx, test_config):
    conn = get_db()
    rows = conn.execute("SELECT keyword, url, title FROM links ORDER BY keyword").fetchall()
    assert [row["keyword"] for row in rows] == ["admin", "home", "lists"]
    base_url = f"http://{test_config.host}:{test_config.port}"
    expected = {
        "home": base_url,
        "lists": f"{base_url}/lists",
        "admin": f"{base_url}/admin",
    }
    assert {row["keyword"]: row["url"] for row in rows} == expected
    assert {row["keyword"]: row["title"] for row in rows} == {
        "home": "Home",
        "lists": "Lists",
        "admin": "Admin",
    }


def test_ensure_seed_links_skips_when_existing(tmp_path):
    conn = sqlite3.connect(tmp_path / "links.sqlite")
    conn.row_factory = sqlite3.Row
    ensure_links_schema(conn)
    conn.execute("INSERT INTO links(keyword, url) VALUES ('gh', 'https://github.com')")
    conn.commit()
    inserted = ensure_seed_links(conn, base_url="http://localhost:5000")
    assert inserted is False
    count = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    assert count == 1
    conn.close()


def test_build_seed_base_url_handles_scheme():
    from backend.app import db as db_mod

    assert db_mod._build_seed_base_url("http://localhost", 5000) == "http://localhost:5000"
    assert db_mod._build_seed_base_url("https://example.com:9000", 5000) == "https://example.com:9000"


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
    ensure_opensearch_columns(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(links)")}
    assert "search_enabled" in columns
    assert "opensearch_doc_url" in columns
    assert "opensearch_template" in columns
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


def test_ensure_admin_users_schema_creates_table(app_ctx):
    conn = get_db()
    ensure_admin_users_schema(conn)
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='admin_users'").fetchone()
    assert row["name"] == "admin_users"
    close_db(None)


def test_db_base_dir_handles_frozen(monkeypatch, tmp_path):
    from backend.app import db as db_mod

    monkeypatch.setattr(db_mod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(db_mod.sys, "executable", str(tmp_path / "app.exe"), raising=False)
    assert db_mod._base_dir() == str(tmp_path)
