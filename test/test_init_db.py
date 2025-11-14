import builtins
import csv
import importlib
import sqlite3
import sys
from pathlib import Path

import init_db
import pytest


def test_init_db_default_path_windows_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(init_db.sys, "platform", "win32", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(init_db.Path, "home", lambda: tmp_path)
    expected = tmp_path / "AppData" / "Roaming" / "go-search-engine" / "links.db"
    assert init_db._default_db_path() == str(expected)


def test_init_db_default_path_windows_appdata(monkeypatch, tmp_path):
    monkeypatch.setattr(init_db.sys, "platform", "win32", raising=False)
    appdata = tmp_path / "AppData"
    localdata = tmp_path / "LocalAppData"
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(localdata))
    expected = appdata / "go-search-engine" / "links.db"
    assert init_db._default_db_path() == str(expected)


def test_init_db_default_path_darwin(monkeypatch, tmp_path):
    monkeypatch.setattr(init_db.sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(init_db.Path, "home", lambda: tmp_path)
    expected = tmp_path / "Library" / "Application Support" / "go-search-engine" / "links.db"
    assert init_db._default_db_path() == str(expected)


def test_init_db_default_path_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(init_db.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(init_db.Path, "home", lambda: tmp_path)
    expected = tmp_path / ".local" / "share" / "go-search-engine" / "links.db"
    assert init_db._default_db_path() == str(expected)


def test_ensure_schema_creates_links_table(tmp_path):
    db_file = tmp_path / "links.sqlite"
    conn = sqlite3.connect(db_file)
    init_db.ensure_schema(conn)
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='links'").fetchone()
    assert row[0] == "links"
    columns = {info[1] for info in conn.execute("PRAGMA table_info(links)")}
    assert "search_enabled" in columns
    conn.close()


def test_import_csv_inserts_rows(tmp_path):
    db_file = tmp_path / "links.sqlite"
    conn = sqlite3.connect(db_file)
    init_db.ensure_schema(conn)

    csv_file = tmp_path / "links.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["keyword", "title", "url"])
        writer.writerow(["gh", "GitHub", "https://github.com"])
        writer.writerow(["", "", ""])
        writer.writerow(["gh", "Duplicate", "https://github.com"])
        writer.writerow(["docs", "Docs", "https://docs.example"])

    init_db.import_csv(conn, csv_file)
    rows = conn.execute("SELECT keyword FROM links ORDER BY keyword").fetchall()
    assert [r[0] for r in rows] == ["docs", "gh"]
    conn.close()


def test_main_initializes_database(tmp_path, monkeypatch):
    db_file = tmp_path / "links.sqlite"
    csv_path = tmp_path / "links.csv"
    csv_path.write_text("keyword,title,url\nhome,Home,https://example.com\n", encoding="utf-8")

    monkeypatch.setattr(init_db, "DB_PATH", str(db_file), raising=False)

    captured = []

    def fake_import_csv(conn, path):
        captured.append((Path(path).name, conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]))

    monkeypatch.setattr(init_db, "import_csv", fake_import_csv)
    monkeypatch.setattr(sys, "argv", ["init_db.py", str(csv_path)], raising=False)

    init_db.main()
    assert db_file.exists()
    assert captured[0][0] == "links.csv"
    conn = sqlite3.connect(db_file)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(links)")}
    assert "search_enabled" in cols
    conn.close()


def test_init_db_import_fallback(monkeypatch, tmp_path):
    original = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "backend.app.db":
            raise ImportError("boom")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    module = importlib.reload(init_db)
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    module.ensure_schema(conn)
    module.ensure_lists_schema(conn)
    conn.execute("DROP TABLE IF EXISTS links")
    conn.execute(
        """
        CREATE TABLE links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          keyword TEXT NOT NULL,
          url TEXT NOT NULL,
          title TEXT
        );
        """
    )
    module.ensure_search_flag_column(conn)
    importlib.reload(init_db)


def test_fallback_helpers_create_schema(tmp_path):
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    init_db._fallback_ensure_lists_schema(conn)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"lists", "link_lists"}.issubset(tables)

    conn.execute("DROP TABLE IF EXISTS links")
    conn.execute(
        """
        CREATE TABLE links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          keyword TEXT NOT NULL,
          url TEXT NOT NULL,
          title TEXT
        );
        """
    )
    init_db._fallback_ensure_search_flag_column(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(links)")}
    assert "search_enabled" in cols
    conn.close()


def test_init_db_fallback_creates_link_lists(monkeypatch, tmp_path):
    original = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "backend.app.db":
            raise ImportError("boom")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    module = importlib.reload(init_db)
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    module.ensure_lists_schema(conn)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"lists", "link_lists"}.issubset(tables)
    conn.close()
    importlib.reload(init_db)


def test_main_missing_csv_exits(monkeypatch, tmp_path):
    db_file = tmp_path / "db.sqlite"
    monkeypatch.setattr(init_db, "DB_PATH", str(db_file), raising=False)
    monkeypatch.setattr(sys, "argv", ["init_db.py", str(tmp_path / "missing.csv")], raising=False)
    with pytest.raises(SystemExit):
        init_db.main()


def test_main_no_args_prints(monkeypatch, tmp_path, capsys):
    db_file = tmp_path / "db.sqlite"
    monkeypatch.setattr(init_db, "DB_PATH", str(db_file), raising=False)
    monkeypatch.setattr(sys, "argv", ["init_db.py"], raising=False)
    init_db.main()
    out = capsys.readouterr().out
    assert "Initialized DB at" in out
