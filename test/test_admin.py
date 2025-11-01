import json

from backend.app import admin


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
    db_conn.execute(
        "INSERT INTO links(keyword, url, title) VALUES ('gh','https://github.com','GitHub')"
    )
    db_conn.commit()
    rv = client.get("/admin/", query_string={"edit": "gh"})
    assert rv.status_code == 200
    assert b"value=\"https://github.com\"" in rv.data


def test_admin_config_get_and_post(client):
    rv = client.get("/admin/config")
    assert rv.status_code == 200

    cfg_path = admin._discover_config_path()
    data = {
        "host": "0.0.0.0",
        "port": "6000",
        "debug": "on",
        "db_path": "db.sqlite",
        "allow_files": "on",
        "fallback_url": "https://duck.example/?q={q}",
        "file_allow": "/data\n/tmp",
    }
    rv = client.post("/admin/config", data=data, follow_redirects=True)
    assert rv.status_code == 200

    blob = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert blob["host"] == "0.0.0.0"
    assert blob["debug"] is True
    assert blob["port"] == 6000
    assert blob["file-allow"] == ["/data", "/tmp"]


def test_admin_link_add_edit_delete(client, db_conn):
    data = {"keyword": "gh", "url": "https://github.com", "title": "GitHub"}
    rv = client.post("/admin/add", data=data)
    assert rv.status_code == 302

    row = db_conn.execute("SELECT title FROM links WHERE keyword='gh'").fetchone()
    assert row["title"] == "GitHub"

    rv = client.post(
        "/admin/update",
        data={
            "original_keyword": "gh",
            "keyword": "git",
            "url": "https://github.com/home",
            "title": "Hub",
        },
    )
    assert rv.status_code == 302
    row = db_conn.execute("SELECT url FROM links WHERE keyword='git'").fetchone()
    assert row["url"] == "https://github.com/home"

    rv = client.post("/admin/delete", data={"keyword": "git"})
    assert rv.status_code == 302
    assert db_conn.execute("SELECT count(*) AS c FROM links").fetchone()["c"] == 0


def test_admin_add_validation_and_duplicate(client, db_conn):
    rv = client.post("/admin/add", data={"keyword": "", "url": ""})
    assert rv.status_code == 400

    client.post("/admin/add", data={"keyword": "gh", "url": "https://github.com"})
    rv = client.post("/admin/add", data={"keyword": "gh", "url": "https://github.com"})
    assert rv.status_code == 400


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


def test_admin_list_add_validation_and_duplicates(client):
    rv = client.post("/admin/list-add", data={"name": "", "slug": ""})
    assert rv.status_code == 400

    rv = client.post("/admin/list-add", data={"slug": "my-slug"})
    assert rv.status_code == 302
    row = client.post("/admin/list-add", data={"name": "My Slug"})
    assert row.status_code == 400


def test_admin_list_add_link_conflict(client, db_conn):
    db_conn.execute(
        "INSERT INTO links(keyword, url) VALUES ('dev-projects','https://example.com')"
    )
    db_conn.commit()
    rv = client.post("/admin/list-add", data={"name": "Dev Projects"})
    assert rv.status_code == 302  # success despite link conflict


def test_admin_set_lists_missing_link(client):
    rv = client.post("/admin/set-lists", data={"keyword": "missing", "slugs": "one"})
    assert rv.status_code == 404


def test_admin_list_delete_validation(client):
    rv = client.post("/admin/list-delete", data={"slug": ""})
    assert rv.status_code == 400

    rv = client.post("/admin/list-delete", data={"slug": "missing"})
    assert rv.status_code == 404
