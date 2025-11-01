import csv
import os
import sqlite3
import sys
from pathlib import Path

import pytest

import init_db
import importlib
import builtins


def test_ensure_schema_creates_links_table(tmp_path):
    db_file = tmp_path / "links.sqlite"
    conn = sqlite3.connect(db_file)
    init_db.ensure_schema(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='links'"
    ).fetchone()
    assert row[0] == "links"
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


def test_init_db_import_fallback(monkeypatch, tmp_path):
    original = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "backend.app.db":
            raise ImportError("boom")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    module = importlib.reload(init_db)
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    module.ensure_lists_schema(conn)
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
