import base64
import json
import os
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from backend.app import main, opensearch
from backend.app.db import ensure_admin_users_schema
from werkzeug.security import generate_password_hash


def add_link(conn, keyword, url, title=None, search_enabled=False):
    conn.execute(
        "INSERT INTO links(keyword, url, title, search_enabled) VALUES (?, ?, ?, ?)",
        (keyword, url, title, int(search_enabled)),
    )
    conn.commit()


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


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


def test_export_shortcuts_csv(client, db_conn):
    add_link(db_conn, "gh", "https://github.com", "GitHub", search_enabled=True)
    add_list(db_conn, "dev", "Dev")
    link_to_list(db_conn, "gh", "dev")
    rv = client.get("/export/shortcuts.csv")
    assert rv.status_code == 200
    assert rv.mimetype == "text/csv"
    disposition = rv.headers.get("Content-Disposition", "")
    assert "attachment" in disposition
    assert "shortcuts.csv" in disposition
    body = rv.data.decode("utf-8").splitlines()
    assert body[0] == "keyword,title,url,search_enabled,lists"
    assert any(line.startswith("gh,GitHub,https://github.com,1,dev") for line in body[1:])


def test_export_shortcuts_requires_admin_auth(client, db_conn, test_config):
    test_config.admin_auth_enabled = True
    ensure_admin_users_schema(db_conn)
    db_conn.execute(
        "INSERT INTO admin_users(username, password_hash, is_active) VALUES (?, ?, 1)",
        ("admin", generate_password_hash("secret")),
    )
    db_conn.commit()
    add_link(db_conn, "gh", "https://github.com", "GitHub", search_enabled=True)

    rv = client.get("/export/shortcuts.csv")
    assert rv.status_code == 302
    assert rv.headers["Location"].endswith("/")

    headers = _basic_auth("admin", "secret")
    rv = client.get("/export/shortcuts.csv", headers=headers)
    assert rv.status_code == 200


def test_export_shortcuts_redirects_when_user_missing_auth(client, db_conn, test_config):
    test_config.admin_auth_enabled = True
    ensure_admin_users_schema(db_conn)
    db_conn.execute(
        "INSERT INTO admin_users(username, password_hash, is_active) VALUES (?, ?, 1)",
        ("admin", generate_password_hash("secret")),
    )
    db_conn.commit()

    rv = client.get("/export/shortcuts.csv")
    assert rv.status_code == 302
    assert rv.headers["Location"].endswith("/")

    rv = client.get("/export/shortcuts.csv", headers=_basic_auth("admin", "wrong"))
    assert rv.status_code == 302
    assert rv.headers["Location"].endswith("/")


def test_import_shortcuts_redirects_on_post_without_auth(client, db_conn, test_config):
    test_config.admin_auth_enabled = True
    ensure_admin_users_schema(db_conn)
    db_conn.execute(
        "INSERT INTO admin_users(username, password_hash, is_active) VALUES (?, ?, 1)",
        ("admin", generate_password_hash("secret")),
    )
    db_conn.commit()

    rv = client.post("/import/shortcuts", data={})
    assert rv.status_code == 302
    assert rv.headers["Location"].endswith("/")


def test_import_shortcuts_rejects_missing_csrf(app_ctx):
    raw_client = app_ctx.test_client()
    rv = raw_client.post(
        "/import/shortcuts", data={"file": (BytesIO(b"keyword,url\nx,https://x"), "shortcuts.csv")}
    )
    assert rv.status_code == 400


def test_import_shortcuts_csv(client, db_conn):
    add_link(db_conn, "gh", "https://github.com", "GitHub")
    add_list(db_conn, "dev", "Dev")
    link_to_list(db_conn, "gh", "dev")

    csv_payload = "\n".join(
        [
            "keyword,title,url,search_enabled,lists",
            ",Skip Row,https://should-skip.example,1,",
            "gh,GitHub Updated,https://github.com/,1,dev",
            "docs,Docs,https://example.com/docs,0,help",
        ]
    ).encode("utf-8")
    data = {"file": (BytesIO(csv_payload), "shortcuts.csv")}
    rv = client.post("/import/shortcuts", data=data)
    assert rv.status_code == 302
    assert rv.headers["Location"].endswith("/")

    # Existing link should be updated with newest data.
    existing = db_conn.execute(
        "SELECT title, search_enabled FROM links WHERE keyword=?",
        ("gh",),
    ).fetchone()
    assert existing["title"] == "GitHub Updated"
    assert existing["search_enabled"] == 0
    assert (
        db_conn.execute(
            "SELECT url FROM links WHERE keyword=?",
            ("gh",),
        ).fetchone()["url"]
        == "https://github.com/"
    )
    link_dev = db_conn.execute(
        """
        SELECT 1 FROM link_lists ll
        JOIN lists li ON li.id = ll.list_id
        WHERE ll.link_id = (SELECT id FROM links WHERE keyword=?) AND li.slug=?
        """,
        ("gh", "dev"),
    ).fetchone()
    assert link_dev is not None

    # New link should be inserted with its list relationship.
    new_link = db_conn.execute(
        "SELECT id, title, url, search_enabled FROM links WHERE keyword=?",
        ("docs",),
    ).fetchone()
    assert new_link["title"] == "Docs"
    assert new_link["url"] == "https://example.com/docs"
    assert new_link["search_enabled"] == 0

    help_list = db_conn.execute(
        "SELECT id FROM lists WHERE slug=?",
        ("help",),
    ).fetchone()
    assert help_list is not None

    junction = db_conn.execute(
        "SELECT 1 FROM link_lists WHERE link_id=? AND list_id=?",
        (new_link["id"], help_list["id"]),
    ).fetchone()
    assert junction is not None


def test_import_shortcuts_requires_file(client):
    rv = client.post("/import/shortcuts")
    assert rv.status_code == 400


def test_import_shortcuts_with_empty_file(client, db_conn):
    rv = client.post("/import/shortcuts", data={"file": (BytesIO(b""), "empty.csv")})
    assert rv.status_code == 302
    count = db_conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    assert count == 3


def test_import_shortcuts_with_blank_content(client, db_conn):
    rv = client.post("/import/shortcuts", data={"file": (BytesIO(b"   \n "), "blank.csv")})
    assert rv.status_code == 302
    count = db_conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    assert count == 3


def test_import_shortcuts_prioritises_new_keyword_on_url_conflict(client, db_conn):
    add_link(db_conn, "gh", "https://github.com", "GitHub")
    add_link(db_conn, "old", "https://github.com", "Alias")
    csv_payload = "\n".join(
        [
            "keyword,title,url,search_enabled,lists",
            "github,GitHub,https://github.com,1,",
        ]
    ).encode("utf-8")
    rv = client.post("/import/shortcuts", data={"file": (BytesIO(csv_payload), "shortcuts.csv")})
    assert rv.status_code == 302
    keywords = {row["keyword"] for row in db_conn.execute("SELECT keyword FROM links").fetchall()}
    assert keywords == {"admin", "home", "lists", "github"}
    row = db_conn.execute(
        "SELECT keyword, search_enabled FROM links WHERE lower(url)=lower(?)",
        ("https://github.com",),
    ).fetchone()
    assert row["keyword"] == "github"
    assert row["search_enabled"] == 0


def test_import_shortcuts_replaces_existing_lists(client, db_conn):
    add_link(db_conn, "gh", "https://github.com", "GitHub")
    add_list(db_conn, "dev", "Dev")
    add_list(db_conn, "docs", "Docs")
    link_to_list(db_conn, "gh", "dev")
    link_to_list(db_conn, "gh", "docs")
    csv_payload = "\n".join(
        [
            "keyword,title,url,search_enabled,lists",
            "gh,GitHub,https://github.com,0,",
        ]
    ).encode("utf-8")
    rv = client.post("/import/shortcuts", data={"file": (BytesIO(csv_payload), "shortcuts.csv")})
    assert rv.status_code == 302
    remaining = db_conn.execute(
        "SELECT COUNT(*) FROM link_lists WHERE link_id = (SELECT id FROM links WHERE keyword=?)",
        ("gh",),
    ).fetchone()[0]
    assert remaining == 0


def test_go_requires_query(client):
    rv = client.get("/go")
    assert rv.status_code == 400


def test_go_exact_match_redirects(client, db_conn):
    add_link(db_conn, "gh", "https://github.com", "GitHub")
    rv = client.get("/go", query_string={"q": "gh"})
    assert rv.status_code == 302
    assert rv.headers["Location"] == "https://github.com"


def test_go_bang_search_redirects_when_enabled(client, db_conn):
    add_link(db_conn, "gh", "https://github.com", "GitHub", search_enabled=True)
    db_conn.execute(
        "UPDATE links SET opensearch_doc_url=?, opensearch_template=? WHERE keyword='gh'",
        ("https://github.com/opensearch.xml", "https://github.com/search?q={searchTerms}"),
    )
    db_conn.commit()
    rv = client.get("/go", query_string={"q": "!gh cats & dogs"})
    assert rv.status_code == 302
    assert rv.headers["Location"] == "https://github.com/search?q=cats+%26+dogs"


def test_go_bang_falls_back_when_disabled(client, db_conn):
    add_link(db_conn, "gh", "https://github.com", "GitHub", search_enabled=False)
    rv = client.get("/go", query_string={"q": "!gh cats"})
    assert rv.status_code == 302
    assert rv.headers["Location"] == "https://github.com"


def test_go_bang_falls_back_when_lookup_fails(client, db_conn):
    add_link(db_conn, "gh", "https://github.com", "GitHub", search_enabled=True)
    rv = client.get("/go", query_string={"q": "!gh cats"})
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


def test_opensearch_suggest_matches_keyword_substring(client, db_conn):
    add_link(db_conn, "github", "https://github.com", "GitHub")
    rv = client.get("/opensearch/suggest", query_string={"q": "hub"})
    assert rv.status_code == 200
    data = json.loads(rv.data)
    assert "github" in data[1]


def test_opensearch_suggest_matches_title_substring(client, db_conn):
    add_link(db_conn, "hs", "https://hubspot.com", "HubSpot")
    rv = client.get("/opensearch/suggest", query_string={"q": "spot"})
    assert rv.status_code == 200
    data = json.loads(rv.data)
    assert "hs" in data[1]


def test_opensearch_suggest_matches_title_multi_token_short_query(client, db_conn):
    add_link(db_conn, "go", "https://example.com", "Go Search")
    rv = client.get("/opensearch/suggest", query_string={"q": "go se"})
    assert rv.status_code == 200
    data = json.loads(rv.data)
    assert "go" in data[1]


def test_opensearch_suggest_blank_query(client):
    rv = client.get("/opensearch/suggest")
    assert rv.status_code == 200
    assert rv.mimetype == "application/x-suggestions+json"
    assert json.loads(rv.data) == ["", [], [], []]


def test_lookup_opensearch_search_url_interpolates(monkeypatch):
    opensearch._get_opensearch_template.cache_clear()
    xml = """<?xml version='1.0'?>
    <OpenSearchDescription xmlns='http://a9.com/-/spec/opensearch/1.1/'>
      <Url type='text/html' method='get' template='/search?q={searchTerms}&amp;lang=en{&amp;foo?}' />
    </OpenSearchDescription>
    """

    def fake_download(url):
        assert url == "https://example.com/opensearch.xml"
        return xml

    monkeypatch.setattr(opensearch, "_download_opensearch_document", fake_download)
    result = opensearch._lookup_opensearch_search_url("https://example.com/home", "cats & dogs")
    assert result == "https://example.com/search?q=cats+%26+dogs&lang=en"
    assert opensearch._lookup_opensearch_search_url("file://local", "cats") is None
    opensearch._get_opensearch_template.cache_clear()


def test_opensearch_document_url_handles_paths():
    assert (
        opensearch._opensearch_document_url("https://example.com/opensearch.xml")
        == "https://example.com/opensearch.xml"
    )
    assert opensearch._opensearch_document_url("file:///tmp/site.xml") is None


def test_download_opensearch_document(monkeypatch):
    class FakeResponse:
        def __init__(self):
            self.encoding = "utf-8"
            self.content = b"<root/>"

    monkeypatch.setattr(opensearch, "_http_get", lambda url: FakeResponse())
    text = opensearch._download_opensearch_document("https://example.com/opensearch.xml")
    assert text == "<root/>"


def test_get_opensearch_template_handles_error(monkeypatch):
    opensearch._get_opensearch_template.cache_clear()

    def boom(_url):
        raise RuntimeError("boom")

    monkeypatch.setattr(opensearch, "_download_opensearch_document", boom)
    assert opensearch._get_opensearch_template("https://example.com/opensearch.xml") is None
    opensearch._get_opensearch_template.cache_clear()


def test_http_get_fallback(monkeypatch):
    class BadResp:
        status_code = 403

    monkeypatch.setattr(opensearch, "_HTTP_CLIENT", SimpleNamespace(get=lambda _url: BadResp()))
    monkeypatch.setattr(opensearch, "tls_client", None, raising=False)

    class GoodCurlResp:
        status_code = 200
        content = b"ok"
        encoding = "utf-8"

    monkeypatch.setattr(opensearch, "curl_requests", SimpleNamespace(get=lambda *a, **k: GoodCurlResp()))
    resp = opensearch._http_get("https://fallback.example.com")
    assert resp.status_code == 200
    assert resp.content == b"ok"


def test_is_safe_remote_url_blocks_localhost_and_private_ip():
    assert opensearch._is_safe_remote_url("http://localhost/opensearch.xml") is False
    assert opensearch._is_safe_remote_url("https://127.0.0.1/opensearch.xml") is False
    assert opensearch._is_safe_remote_url("https://192.168.1.15/opensearch.xml") is False
    assert opensearch._is_safe_remote_url("http://[::1]/opensearch.xml") is False


def test_is_safe_remote_url_blocks_private_dns_resolution(monkeypatch):
    opensearch._hostname_resolves_public.cache_clear()

    monkeypatch.setattr(
        opensearch.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (
                opensearch.socket.AF_INET,
                opensearch.socket.SOCK_STREAM,
                6,
                "",
                ("10.0.0.8", 443),
            )
        ],
    )
    assert opensearch._is_safe_remote_url("https://internal.example/opensearch.xml") is False
    opensearch._hostname_resolves_public.cache_clear()


def test_http_get_rejects_unsafe_target_before_request(monkeypatch):
    called = {"network_called": False}

    def fake_get(_url):
        called["network_called"] = True
        return SimpleNamespace(status_code=200, content=b"ok", encoding="utf-8", headers={})

    monkeypatch.setattr(opensearch, "_HTTP_CLIENT", SimpleNamespace(get=fake_get))
    assert opensearch._http_get("http://127.0.0.1/secret") is None
    assert called["network_called"] is False


def test_http_get_blocks_redirect_to_private_target(monkeypatch):
    calls = []

    class RedirectResp:
        status_code = 302
        headers = {"Location": "http://127.0.0.1/admin"}

    def fake_get(url, follow_redirects=False):
        calls.append(url)
        return RedirectResp()

    monkeypatch.setattr(opensearch, "_HTTP_CLIENT", SimpleNamespace(get=fake_get))
    monkeypatch.setattr(opensearch, "curl_requests", None)
    monkeypatch.setattr(opensearch, "tls_client", None, raising=False)

    assert opensearch._http_get("https://example.com/start") is None
    assert calls == ["https://example.com/start"]


def test_http_get_no_fallback(monkeypatch):
    class BadResp:
        status_code = 403

    monkeypatch.setattr(opensearch, "_HTTP_CLIENT", SimpleNamespace(get=lambda _url: BadResp()))
    monkeypatch.setattr(opensearch, "curl_requests", None)
    monkeypatch.setattr(opensearch, "tls_client", None, raising=False)
    assert opensearch._http_get("https://blocked.example.com") is None


def test_http_get_tls_client_fallback(monkeypatch):
    class BadResp:
        status_code = 403

    monkeypatch.setattr(opensearch, "_HTTP_CLIENT", SimpleNamespace(get=lambda _url: BadResp()))
    monkeypatch.setattr(opensearch, "curl_requests", None)

    class FakeSession:
        def __init__(self, client_identifier):
            assert client_identifier.startswith("chrome")

        def get(self, url, headers, timeout, allow_redirects):
            return SimpleNamespace(status_code=200, content=b"tls", encoding="utf-8")

    fake_tls = SimpleNamespace(Session=FakeSession)
    monkeypatch.setattr(opensearch, "tls_client", fake_tls)
    resp = opensearch._http_get("https://tls.example.com")
    assert resp.status_code == 200
    assert resp.content == b"tls"


def test_candidate_opensearch_document_urls_from_html(monkeypatch):
    html = (
        "<html><head>"
        "<link rel='search' type='application/opensearchdescription+xml' href='/os.xml'>"
        '<script>StackExchange={opensearchUrl:"/script.xml"};</script>'
        "</head></html>"
    )

    def fake_fetch(url):
        return html if "example.com" in url else None

    monkeypatch.setattr(opensearch, "_fetch_html", fake_fetch)
    docs = opensearch._candidate_opensearch_document_urls("https://example.com/wiki/Foo")
    assert "https://example.com/os.xml" in docs
    assert "https://example.com/script.xml" in docs


def test_lookup_opensearch_uses_discovered_link(monkeypatch):
    html = (
        "<html><head>"
        "<link rel='search' type='application/opensearchdescription+xml' "
        "href='/opensearch_desc.php'>"
        "</head></html>"
    )

    def fake_fetch(url):
        return html if "example.com" in url else None

    def fake_download(url):
        if url.endswith("opensearch_desc.php"):
            return """<?xml version='1.0'?>
<OpenSearchDescription xmlns='http://a9.com/-/spec/opensearch/1.1/'>
  <Url type='text/html' method='get' template='https://example.com/search?q={searchTerms}' />
</OpenSearchDescription>
"""
        raise RuntimeError("missing descriptor")

    monkeypatch.setattr(opensearch, "_fetch_html", fake_fetch)
    monkeypatch.setattr(opensearch, "_download_opensearch_document", fake_download)
    opensearch._get_opensearch_template.cache_clear()
    result = opensearch._lookup_opensearch_search_url("https://example.com/wiki/Foo", "cats")
    assert result == "https://example.com/search?q=cats"
    opensearch._get_opensearch_template.cache_clear()


def test_parse_opensearch_link_hrefs_filters_non_search():
    html = "<html><head><link rel='stylesheet' href='/style.css'></head></html>"
    assert opensearch._parse_opensearch_link_hrefs(html) == []


def test_parse_opensearch_link_hrefs_filters_wrong_type():
    html = "<html><head><link rel='search' type='text/html' href='/ignored.xml'></head></html>"
    assert opensearch._parse_opensearch_link_hrefs(html) == []


def test_parse_opensearch_script_hrefs_extracts():
    html = 'var StackExchange = {opensearchUrl:"\\/search.xml"};'
    assert opensearch._parse_opensearch_script_hrefs(html) == ["/search.xml"]


def test_extract_search_template_variants():
    doc = """<OpenSearchDescription xmlns='http://a9.com/-/spec/opensearch/1.1/'>
    <Url />
    <Url template='/skip' method='post' />
    <Url template='/skip' method='get' type='application/json' />
    <Url template='/skip' method='get' type='text/html' />
    <Url template='/search?q={searchTerms}' method='get' type='text/html' />
    </OpenSearchDescription>"""
    assert opensearch._extract_search_template(doc) == "/search?q={searchTerms}"
    assert opensearch._extract_search_template("not xml") is None
    doc_no_match = """<OpenSearchDescription xmlns='http://a9.com/-/spec/opensearch/1.1/'>
    <Url template='/plain' method='get' type='text/html' />
    </OpenSearchDescription>"""
    assert opensearch._extract_search_template(doc_no_match) is None


def test_strip_optional_placeholders_variants():
    assert opensearch._strip_optional_placeholders("plain") == "plain"
    template = "{keep} {drop?} trailing{"
    assert opensearch._strip_optional_placeholders(template) == "{keep}  trailing{"


def test_build_search_url_requires_placeholder():
    assert opensearch._build_search_url("https://example.com/opensearch.xml", "/search", "cats") is None


def test_lookup_opensearch_requires_terms():
    assert opensearch._lookup_opensearch_search_url("https://example.com", "") is None


def test_lookup_opensearch_handles_missing_template(monkeypatch):
    monkeypatch.setattr(opensearch, "_get_opensearch_template", lambda _url: None)
    assert opensearch._lookup_opensearch_search_url("https://example.com", "cats") is None


def test_refresh_link_opensearch_clears_template_on_failure(app_ctx, db_conn, monkeypatch):
    db_conn.execute(
        """
        INSERT INTO links(keyword, url, title, search_enabled, opensearch_doc_url, opensearch_template)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "gh",
            "https://github.com",
            "GitHub",
            1,
            "https://example.com/opensearch.xml",
            "https://example.com/search?q={searchTerms}",
        ),
    )
    db_conn.commit()

    monkeypatch.setattr(opensearch, "discover_opensearch_template", lambda _url: None)
    link_id = db_conn.execute("SELECT id FROM links WHERE keyword='gh'").fetchone()["id"]
    opensearch.refresh_link_opensearch(db_conn, link_id, "https://github.com")

    row = db_conn.execute(
        "SELECT search_enabled, opensearch_doc_url, opensearch_template FROM links WHERE keyword='gh'"
    ).fetchone()
    assert row["search_enabled"] == 0
    assert row["opensearch_doc_url"] is None
    assert row["opensearch_template"] is None


def test_handle_bang_query_guard_conditions(db_conn):
    db_conn.execute(
        """
        CREATE TABLE IF NOT EXISTS links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          keyword TEXT NOT NULL UNIQUE,
          url TEXT NOT NULL,
          title TEXT,
          search_enabled INTEGER NOT NULL DEFAULT 0,
          opensearch_doc_url TEXT,
          opensearch_template TEXT
        );
        """
    )
    db_conn.commit()
    assert main._handle_bang_query(db_conn, "!") is None
    assert main._handle_bang_query(db_conn, "!    ") is None
    assert main._handle_bang_query(db_conn, "!missing cats") is None


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
    assert rv.status_code == 400
