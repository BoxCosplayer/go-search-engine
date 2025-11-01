from backend.app.db import close_db, ensure_lists_schema, get_db, init_db


def test_get_db_reuses_connection(app_ctx):
    conn1 = get_db()
    conn2 = get_db()
    assert conn1 is conn2
    close_db(None)


def test_init_db_creates_links_table(app_ctx):
    init_db()
    conn = get_db()
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='links'").fetchone()
    assert row["name"] == "links"
    close_db(None)


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
