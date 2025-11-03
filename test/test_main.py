import json
import os
from pathlib import Path

import pytest
from backend.app import main


def add_link(conn, keyword, url, title=None):
    conn.execute(
        "INSERT INTO links(keyword, url, title) VALUES (?, ?, ?)",
        (keyword, url, title),
    )
    conn.commit()


def add_list(conn, slug, name, description=""):
    conn.execute(
        "INSERT INTO lists(slug, name, description) VALUES (?, ?, ?)",
        (slug, name, description or None),
    )
    conn.commit()
    return conn.execute("SELECT id FROM lists WHERE slug=?", (slug,)).fetchone()["id"]


def link_to_list(conn, link_keyword, list_slug):
    link_id = conn.execute("SELECT id FROM links WHERE keyword=?", (link_keyword,)).fetchone()["id"]
    list_id = conn.execute("SELECT id FROM lists WHERE slug=?", (list_slug,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO link_lists(link_id, list_id) VALUES (?, ?)",
        (link_id, list_id),
    )
    conn.commit()


def test_healthz_success(client):
    rv = client.get("/healthz")
    assert rv.status_code == 200
    assert rv.get_json() == {"status": "ok"}


def test_fixture_resource_path_usage(test_config):
    path = main._resource_path("dummy.txt")
    assert path.endswith("dummy.txt")


def test_index_redirects_when_query_present(client):
    rv = client.get("/", query_string={"q": "test"})
    assert rv.status_code == 302
    assert rv.headers["Location"].endswith("/go?q=test")


def test_index_renders_links(client, db_conn):
    add_link(db_conn, "gh", "https://github.com", "GitHub")
    add_list(db_conn, "dev", "Dev")
    link_to_list(db_conn, "gh", "dev")
    rv = client.get("/")
    assert rv.status_code == 200
    assert b"GitHub" in rv.data
    assert b"dev" in rv.data


def test_go_requires_query(client):
    rv = client.get("/go")
    assert rv.status_code == 400


def test_go_exact_match_redirects(client, db_conn):
    add_link(db_conn, "gh", "https://github.com", "GitHub")
    rv = client.get("/go", query_string={"q": "gh"})
    assert rv.status_code == 302
    assert rv.headers["Location"] == "https://github.com"


def test_go_multi_term_query_without_exact_match_returns_not_found(client, db_conn):
    add_link(db_conn, "g", "https://example.com/search?q={q}", "Search")
    rv = client.get("/go", query_string={"q": "g cats"})
    assert rv.status_code == 404
    assert b"No exact match" in rv.data


def test_go_multi_term_exact_keyword_is_not_accessible(client, db_conn):
    add_link(db_conn, "foo bar", "https://example.com")
    rv = client.get("/go", query_string={"q": "foo bar"})
    assert rv.status_code == 404


def test_go_file_link_opens_and_confirms(client, db_conn, monkeypatch, test_config, tmp_path):
    allowed_dir = Path(test_config.file_allow[0])
    target = allowed_dir / "note.txt"
    target.write_text("data", encoding="utf-8")
    add_link(db_conn, "local", target.as_uri(), "Local File")

    opened = []
    monkeypatch.setattr(main, "open_path_with_os", lambda path: opened.append(path))
    rv = client.get("/go", query_string={"q": "local"})

    assert rv.status_code == 200
    assert b"note.txt" in rv.data
    assert opened == [os.path.normpath(str(target))]


def test_go_not_found_renders_suggestions(client, db_conn):
    add_link(db_conn, "gh", "https://github.com", "GitHub")
    rv = client.get("/go", query_string={"q": "nothing"})
    assert rv.status_code == 404
    assert b"nothing" in rv.data
    assert b"https://search.example/" in rv.data


def test_index_includes_opensearch_link(client):
    rv = client.get("/")
    assert rv.status_code == 200
    text = rv.get_data(as_text=True)
    assert 'rel="search"' in text
    assert "opensearch.xml" in text


def test_admin_includes_opensearch_link(client):
    rv = client.get("/admin/")
    assert rv.status_code == 200
    text = rv.get_data(as_text=True)
    assert 'rel="search"' in text
    assert "opensearch.xml" in text


def test_make_tray_image_returns_image():
    img = main._make_tray_image()
    assert img.size == (64, 64)


def test_make_tray_image_missing_font(monkeypatch):
    def raises():
        raise RuntimeError("boom")

    monkeypatch.setattr(main.ImageFont, "load_default", raises)
    monkeypatch.setattr(main.ImageDraw.ImageDraw, "text", lambda self, *args, **kwargs: None, raising=False)
    img = main._make_tray_image()
    assert img.size == (64, 64)


def test_make_tray_image_requires_pillow(monkeypatch):
    monkeypatch.setattr(main, "Image", None)
    monkeypatch.setattr(main, "ImageDraw", None)
    with pytest.raises(RuntimeError):
        main._require_pillow_modules()


def test_base_dir_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(main.sys, "executable", str(tmp_path / "app.exe"), raising=False)
    assert main._base_dir() == str(tmp_path)


def test_resource_path_meipass(monkeypatch, tmp_path):
    target = tmp_path / "resource.txt"
    target.write_text("data", encoding="utf-8")
    monkeypatch.setattr(main, "BASE_DIR", str(tmp_path / "other"), raising=False)
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(main.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(os.path, "exists", lambda path: path == str(target))
    assert main._resource_path("resource.txt").endswith("resource.txt")


def test_resource_path_existing(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "BASE_DIR", str(tmp_path), raising=False)
    target = tmp_path / "config.json"
    target.write_text("{}", encoding="utf-8")
    assert main._resource_path("config.json") == str(target)


def test_resource_path_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "BASE_DIR", str(tmp_path), raising=False)
    path = main._resource_path("missing.txt")
    assert path.endswith("missing.txt")


def test_load_config_missing_file(monkeypatch, tmp_path):
    cfg = tmp_path / "missing.json"
    monkeypatch.setenv("GO_CONFIG_PATH", str(cfg))
    assert main.load_config() == {}


def test_opensearch_description(client):
    rv = client.get("/opensearch.xml")
    assert rv.status_code == 200
    assert rv.mimetype == "application/opensearchdescription+xml"
    text = rv.get_data(as_text=True)
    assert 'template="http://localhost/go?q={searchTerms}"' in text
    assert 'template="http://localhost/opensearch/suggest?q={searchTerms}"' in text


def test_opensearch_suggest_returns_matches(client, db_conn):
    add_link(db_conn, "gh", "https://github.com", "GitHub")
    rv = client.get("/opensearch/suggest", query_string={"q": "g"})
    assert rv.status_code == 200
    assert rv.mimetype == "application/x-suggestions+json"
    data = json.loads(rv.data)
    assert data[0] == "g"
    assert data[1] == ["gh"]
    assert data[2][0] == "GitHub"
    assert data[3][0] == "https://github.com"


def test_opensearch_suggest_blank_query(client):
    rv = client.get("/opensearch/suggest")
    assert rv.status_code == 200
    assert rv.mimetype == "application/x-suggestions+json"
    assert json.loads(rv.data) == ["", [], [], []]


def test_load_config_handles_missing_file(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"debug": true}', encoding="utf-8")
    monkeypatch.setenv("GO_CONFIG_PATH", str(cfg))
    data = main.load_config()
    assert data["debug"] is True


def test_go_bad_file_url(client, db_conn, monkeypatch):
    add_link(db_conn, "local", "file:///::bad", "Bad File")

    def raises(_url):
        raise ValueError("bad")

    monkeypatch.setattr(main, "file_url_to_path", raises)
    rv = client.get("/go", query_string={"q": "local"})
    assert rv.status_code == 400


def test_go_file_not_allowed(client, db_conn, monkeypatch, tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("x", encoding="utf-8")
    add_link(db_conn, "local", path.as_uri(), "File")
    monkeypatch.setattr(main, "ALLOW_FILES", False, raising=False)
    rv = client.get("/go", query_string={"q": "local"}, base_url="http://example.com")
    assert rv.status_code == 403


def test_go_file_path_checks(client, db_conn, monkeypatch, tmp_path):
    path = tmp_path / "missing.txt"
    add_link(db_conn, "local", path.as_uri(), "File")
    monkeypatch.setattr(main, "is_allowed_path", lambda _p: False)
    rv = client.get("/go", query_string={"q": "local"})
    assert rv.status_code == 403

    monkeypatch.setattr(main, "is_allowed_path", lambda _p: True)
    monkeypatch.setattr(os.path, "exists", lambda _p: False)
    rv = client.get("/go", query_string={"q": "local"})
    assert rv.status_code == 404

    monkeypatch.setattr(os.path, "exists", lambda _p: True)

    def raises_open(_p):
        raise RuntimeError("fail")

    monkeypatch.setattr(main, "open_path_with_os", raises_open)
    rv = client.get("/go", query_string={"q": "local"})
    assert rv.status_code == 500


def test_go_exact_redirect_other_scheme(client, db_conn):
    add_link(db_conn, "mailto", "mailto:test@example.com", "Email")
    rv = client.get("/go", query_string={"q": "mailto"})
    assert rv.status_code == 302


def test_healthz_error_path(client, monkeypatch):
    def fail():
        raise RuntimeError("db down")

    monkeypatch.setattr(main, "get_db", fail)
    rv = client.get("/healthz")
    assert rv.status_code == 500
    assert rv.get_json()["status"] == "error"
