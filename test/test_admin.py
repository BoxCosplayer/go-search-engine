import base64
import json

from backend.app.admin import config_routes
from backend.app.admin import home as admin_home
from werkzeug.exceptions import BadRequest
from backend.app.db import ensure_admin_users_schema
from werkzeug.security import generate_password_hash


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


def test_admin_home_lists_links(client, db_conn):
    db_conn.execute(
        "INSERT INTO links(keyword, url, title) VALUES (?, ?, ?)",
        ("gh", "https://github.com", "GitHub"),
    )
    db_conn.commit()
    rv = client.get("/admin/")
    assert rv.status_code == 200
    assert b"GitHub" in rv.data


def test_admin_home_edit_mode(client, db_conn):
    db_conn.execute("INSERT INTO links(keyword, url, title) VALUES ('gh','https://github.com','GitHub')")
    db_conn.commit()
    rv = client.get("/admin/", query_string={"edit": "gh"})
    assert rv.status_code == 200
    assert b'value="https://github.com"' in rv.data


def test_admin_error_handler_renders_message(app_ctx):
    with app_ctx.test_request_context("/admin/"):
        body, status = admin_home._handle_admin_http_error(BadRequest("boom"))
    assert status == 400
    assert "boom" in body


def test_admin_config_get_and_post(client, db_conn):
    rv = client.get("/admin/config")
    assert rv.status_code == 200

    ensure_admin_users_schema(db_conn)
    db_conn.execute(
        "INSERT INTO admin_users(username, password_hash, is_active) VALUES (?, ?, ?)",
        ("admin", generate_password_hash("secret"), 1),
    )
    db_conn.commit()

    cfg_path = config_routes._discover_config_path()
    data = {
        "host": "127.0.0.1",
        "port": "6000",
        "debug": "on",
        "allow_files": "on",
        "admin_auth_enabled": "on",
        "fallback_url": "https://duck.example/?q={q}",
        "file_allow": "/data\n/tmp",
    }
    rv = client.post("/admin/config", data=data, follow_redirects=True)
    assert rv.status_code == 200

    blob = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert blob["host"] == "127.0.0.1"
    assert blob["debug"] is True
    assert blob["port"] == 6000
    assert blob["file-allow"] == ["/data", "/tmp"]
    assert blob["admin-auth-enabled"] is True
    assert "db-path" not in blob


def test_admin_config_rejects_auth_without_users(client):
    cfg_path = config_routes._discover_config_path()
    data = {
        "host": "127.0.0.1",
        "port": "6000",
        "debug": "on",
        "allow_files": "on",
        "admin_auth_enabled": "on",
        "fallback_url": "https://duck.example/?q={q}",
        "file_allow": "/data\n/tmp",
    }
    rv = client.post("/admin/config", data=data, follow_redirects=True)
    assert rv.status_code == 200
    assert b"Create at least one admin user before enabling authentication" in rv.data

    blob = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert blob.get("admin-auth-enabled") is not True


def test_admin_module_reexports(monkeypatch, tmp_path):
    from importlib import reload

    import conftest as test_support

    cfg = test_support.prepare_test_config(monkeypatch, tmp_path)

    import backend.app.admin as admin_pkg

    reloaded = reload(admin_pkg)
    monkeypatch.setattr(reloaded, "_discover_config_path", lambda: cfg._config_path, raising=False)

    assert reloaded.admin_bp.name == "admin"
    assert reloaded.admin_add.__name__ == "admin_add"
    assert reloaded.admin_list_delete.__name__ == "admin_list_delete"


def test_admin_link_add_edit_delete(client, db_conn):
    data = {"keyword": "gh", "url": "https://github.com", "title": "GitHub"}
    rv = client.post("/admin/add", data=data)
    assert rv.status_code == 302

    row = db_conn.execute("SELECT title, search_enabled FROM links WHERE keyword='gh'").fetchone()
    assert row["title"] == "GitHub"
    assert row["search_enabled"] == 0

    rv = client.post(
        "/admin/update",
        data={
            "original_keyword": "gh",
            "keyword": "git",
            "url": "https://github.com/home",
            "title": "Hub",
            "search_enabled": "on",
        },
    )
    assert rv.status_code == 302
    row = db_conn.execute("SELECT url, search_enabled FROM links WHERE keyword='git'").fetchone()
    assert row["url"] == "https://github.com/home"
    assert row["search_enabled"] == 1

    rv = client.post("/admin/delete", data={"keyword": "git"})
    assert rv.status_code == 302
    assert db_conn.execute("SELECT count(*) AS c FROM links").fetchone()["c"] == 3


def test_admin_add_sets_search_flag(client, db_conn):
    data = {
        "keyword": "ddg",
        "url": "https://duckduckgo.com",
        "title": "DuckDuckGo",
        "search_enabled": "on",
    }
    rv = client.post("/admin/add", data=data)
    assert rv.status_code == 302
    row = db_conn.execute("SELECT search_enabled FROM links WHERE keyword='ddg'").fetchone()
    assert row["search_enabled"] == 1


def test_admin_add_validation_and_duplicate(client, db_conn):
    rv = client.post("/admin/add", data={"keyword": "", "url": ""})
    assert rv.status_code == 400
    rv = client.post("/admin/add", data={"keyword": "two words", "url": "https://example.com"})
    assert rv.status_code == 400

    client.post("/admin/add", data={"keyword": "gh", "url": "https://github.com"})
    rv = client.post("/admin/add", data={"keyword": "gh", "url": "https://github.com"})
    assert rv.status_code == 400
    assert b"already exists" in rv.data


def test_admin_delete_requires_keyword(client):
    rv = client.post("/admin/delete", data={"keyword": ""})
    assert rv.status_code == 400


def test_admin_list_flow(client, db_conn):
    # Create link to assign later
    client.post("/admin/add", data={"keyword": "gh", "url": "https://github.com", "title": "GitHub"})

    rv = client.post(
        "/admin/list-add",
        data={"name": "Dev Projects", "description": "desc"},
    )
    assert rv.status_code == 302

    slug = db_conn.execute("SELECT slug FROM lists").fetchone()["slug"]
    assert slug == "dev-projects"

    rv = client.post(
        "/admin/set-lists",
        data={"keyword": "gh", "slugs": f"{slug},extra"},
    )
    assert rv.status_code == 302

    rows = db_conn.execute("SELECT COUNT(*) AS c FROM link_lists").fetchone()["c"]
    assert rows == 2

    rv = client.post("/admin/list-delete", data={"slug": "extra"})
    assert rv.status_code == 302

    rv = client.post("/admin/list-delete", data={"slug": slug})
    assert rv.status_code == 302
    count = db_conn.execute("SELECT COUNT(*) AS c FROM links WHERE lower(keyword)=lower(?)", (slug,)).fetchone()[
        "c"
    ]
    assert count == 0


def test_admin_update_validation_and_errors(client):
    rv = client.post("/admin/update", data={"original_keyword": "", "keyword": "", "url": ""})
    assert rv.status_code == 400

    rv = client.post(
        "/admin/update",
        data={"original_keyword": "missing", "keyword": "x", "url": "https://example.com"},
    )
    assert rv.status_code == 404

    client.post("/admin/add", data={"keyword": "a", "url": "https://a.com"})
    client.post("/admin/add", data={"keyword": "b", "url": "https://b.com"})
    rv = client.post(
        "/admin/update",
        data={
            "original_keyword": "a",
            "keyword": "b",
            "url": "https://example.com",
        },
    )
    assert rv.status_code == 400
    rv = client.post(
        "/admin/update",
        data={
            "original_keyword": "a",
            "keyword": "multi term",
            "url": "https://example.com",
        },
    )
    assert rv.status_code == 400


def test_admin_list_add_validation_and_duplicates(client):
    rv = client.post("/admin/list-add", data={"name": "", "slug": ""})
    assert rv.status_code == 400

    rv = client.post("/admin/list-add", data={"slug": "my-slug"})
    assert rv.status_code == 302
    row = client.post("/admin/list-add", data={"name": "My Slug"})
    assert row.status_code == 400


def test_admin_list_add_link_conflict(client, db_conn):
    db_conn.execute("INSERT INTO links(keyword, url) VALUES ('dev-projects','https://example.com')")
    db_conn.commit()
    rv = client.post("/admin/list-add", data={"name": "Dev Projects"})
    assert rv.status_code == 302  # success despite link conflict


def test_admin_set_lists_missing_link(client):
    rv = client.post("/admin/set-lists", data={"keyword": "missing", "slugs": "one"})
    assert rv.status_code == 404


def test_admin_set_lists_auto_list_link(client, db_conn):
    client.post("/admin/add", data={"keyword": "gh", "url": "https://github.com"})

    rv = client.post("/admin/set-lists", data={"keyword": "gh", "slugs": "new-list"})
    assert rv.status_code == 302

    list_row = db_conn.execute("SELECT slug FROM lists WHERE slug='new-list'").fetchone()
    assert list_row is not None

    link_row = db_conn.execute("SELECT url, title FROM links WHERE keyword='new-list'").fetchone()
    assert link_row is not None
    assert link_row["url"].endswith("/lists/new-list")
    assert link_row["title"] == "List - New List"


def test_admin_list_delete_validation(client):
    rv = client.post("/admin/list-delete", data={"slug": ""})
    assert rv.status_code == 400

    rv = client.post("/admin/list-delete", data={"slug": "missing"})
    assert rv.status_code == 404


def test_admin_auth_bootstrap_flow(client, db_conn, test_config):
    test_config.admin_auth_enabled = True

    rv = client.get("/admin/")
    assert rv.status_code == 401
    assert "Basic" in rv.headers.get("WWW-Authenticate", "")

    bad_header = _basic_auth("bad name", "pass123")
    rv = client.get("/admin/", headers=bad_header)
    assert rv.status_code == 401
    assert db_conn.execute("SELECT COUNT(*) AS c FROM admin_users").fetchone()["c"] == 0

    empty_header = _basic_auth("admin", "")
    rv = client.get("/admin/", headers=empty_header)
    assert rv.status_code == 401
    assert db_conn.execute("SELECT COUNT(*) AS c FROM admin_users").fetchone()["c"] == 0

    header = _basic_auth("admin", "pass123")
    rv = client.get("/admin/", headers=header)
    assert rv.status_code == 200
    row = db_conn.execute("SELECT username FROM admin_users").fetchone()
    assert row["username"] == "admin"


def test_admin_auth_rejects_invalid_and_inactive(client, db_conn, test_config):
    test_config.admin_auth_enabled = True
    ensure_admin_users_schema(db_conn)
    db_conn.execute(
        "INSERT INTO admin_users(username, password_hash, is_active) VALUES (?, ?, ?)",
        ("admin", generate_password_hash("secret"), 1),
    )
    db_conn.commit()

    rv = client.get("/admin/")
    assert rv.status_code == 401

    rv = client.get("/admin/", headers=_basic_auth("admin", "wrong"))
    assert rv.status_code == 401

    db_conn.execute("UPDATE admin_users SET is_active=0 WHERE username='admin'")
    db_conn.commit()
    rv = client.get("/admin/", headers=_basic_auth("admin", "secret"))
    assert rv.status_code == 401

    db_conn.execute("UPDATE admin_users SET is_active=1 WHERE username='admin'")
    db_conn.commit()
    rv = client.get("/admin/", headers=_basic_auth("admin", "secret"))
    assert rv.status_code == 200


def test_admin_users_management_routes(client, db_conn, test_config):
    test_config.admin_auth_enabled = True
    ensure_admin_users_schema(db_conn)
    db_conn.execute(
        "INSERT INTO admin_users(username, password_hash, is_active) VALUES (?, ?, ?)",
        ("admin", generate_password_hash("secret"), 1),
    )
    db_conn.commit()
    headers = _basic_auth("admin", "secret")

    rv = client.get("/admin/users", headers=headers)
    assert rv.status_code == 200

    rv = client.post(
        "/admin/users/add",
        data={"username": "", "password": ""},
        headers=headers,
    )
    assert rv.status_code == 302
    assert "error=" in rv.headers["Location"]

    rv = client.post(
        "/admin/users/add",
        data={"username": "second", "password": "pass123"},
        headers=headers,
    )
    assert rv.status_code == 302

    rv = client.post(
        "/admin/users/add",
        data={"username": "second", "password": "pass123"},
        headers=headers,
    )
    assert rv.status_code == 302
    assert "error=" in rv.headers["Location"]

    rv = client.post(
        "/admin/users/password",
        data={"username": "second", "password": "newpass"},
        headers=headers,
    )
    assert rv.status_code == 302

    rv = client.post(
        "/admin/users/password",
        data={"username": "admin", "password": ""},
        headers=headers,
    )
    assert rv.status_code == 302
    assert "error=" in rv.headers["Location"]

    rv = client.post(
        "/admin/users/password",
        data={"username": "missing", "password": "newpass"},
        headers=headers,
    )
    assert rv.status_code == 302
    assert "error=" in rv.headers["Location"]

    rv = client.post(
        "/admin/users/toggle",
        data={"username": "second", "is_active": "0"},
        headers=headers,
    )
    assert rv.status_code == 302

    rv = client.post(
        "/admin/users/toggle",
        data={"username": "bad name", "is_active": "0"},
        headers=headers,
    )
    assert rv.status_code == 302
    assert "error=" in rv.headers["Location"]

    rv = client.post(
        "/admin/users/toggle",
        data={"username": "missing", "is_active": "0"},
        headers=headers,
    )
    assert rv.status_code == 302
    assert "error=" in rv.headers["Location"]

    rv = client.post(
        "/admin/users/toggle",
        data={"username": "admin", "is_active": "0"},
        headers=headers,
    )
    assert rv.status_code == 302
    assert "error=" in rv.headers["Location"]

    rv = client.post(
        "/admin/users/delete",
        data={"username": "missing"},
        headers=headers,
    )
    assert rv.status_code == 302
    assert "error=" in rv.headers["Location"]

    rv = client.post(
        "/admin/users/delete",
        data={"username": ""},
        headers=headers,
    )
    assert rv.status_code == 302
    assert "error=" in rv.headers["Location"]

    rv = client.post(
        "/admin/users/delete",
        data={"username": "second"},
        headers=headers,
    )
    assert rv.status_code == 302
