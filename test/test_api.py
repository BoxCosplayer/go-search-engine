from backend.app import api


def test_links_endpoint_lists_existing(client, test_config):
    rv = client.get("/api/links")
    assert rv.status_code == 200
    data = rv.get_json()
    keywords = [item["keyword"] for item in data["links"]]
    assert keywords == ["admin", "home", "lists"]
    base_url = f"http://{test_config.host}:{test_config.port}"
    url_map = {item["keyword"]: item["url"] for item in data["links"]}
    assert url_map == {
        "admin": f"{base_url}/admin",
        "home": base_url,
        "lists": f"{base_url}/lists",
    }


def test_links_post_and_get(client, db_conn):
    payload = {
        "keyword": "gh",
        "url": "https://github.com",
        "title": "GitHub",
        "search_enabled": True,
    }
    rv = client.post("/api/links", json=payload)
    assert rv.status_code == 200
    assert rv.get_json() == {"ok": True}

    rv = client.get("/api/links")
    data = rv.get_json()
    link_map = {item["keyword"]: item for item in data["links"]}
    assert link_map["gh"]["search_enabled"] is True


def test_links_post_defaults_search_disabled(client):
    payload = {"keyword": "ddg", "url": "https://duckduckgo.com"}
    rv = client.post("/api/links", json=payload)
    assert rv.status_code == 200
    rv = client.get("/api/links/ddg")
    assert rv.get_json()["link"]["search_enabled"] is False


def test_links_post_accepts_string_flag(client, db_conn):
    payload = {"keyword": "yt", "url": "https://youtube.com", "search_enabled": "yes"}
    rv = client.post("/api/links", json=payload)
    assert rv.status_code == 200
    row = db_conn.execute("SELECT search_enabled FROM links WHERE keyword='yt'").fetchone()
    assert row["search_enabled"] == 1


def test_links_post_validation_errors(client):
    rv = client.post("/api/links", json={"keyword": "", "url": ""})
    assert rv.status_code == 400
    rv = client.post("/api/links", json={"keyword": "gh", "url": "ftp://example"})
    assert rv.status_code == 400
    rv = client.post("/api/links", json={"keyword": "two words", "url": "https://example.com"})
    assert rv.status_code == 400


def test_links_post_requires_json_object(client):
    rv = client.post("/api/links", data="nope")
    assert rv.status_code == 400
    assert rv.get_json()["error"] == "Expected application/json"

    rv = client.post("/api/links", json=["nope"])
    assert rv.status_code == 400
    assert rv.get_json()["error"] == "JSON object required"


def test_links_post_duplicate_error(client):
    payload = {"keyword": "gh", "url": "https://github.com"}
    client.post("/api/links", json=payload)
    rv = client.post("/api/links", json=payload)
    assert rv.status_code == 400


def test_get_link_and_update_and_delete(client):
    client.post("/api/links", json={"keyword": "gh", "url": "https://github.com"})

    rv = client.get("/api/links/gh")
    assert rv.status_code == 200
    assert rv.get_json()["link"]["url"] == "https://github.com"
    assert rv.get_json()["link"]["search_enabled"] is False

    rv = client.put(
        "/api/links/gh",
        json={
            "url": "https://github.com/home",
            "title": "Hub",
            "keyword": "git",
            "search_enabled": 1,
        },
    )
    assert rv.status_code == 200
    body = rv.get_json()["link"]
    assert body["keyword"] == "git"
    assert body["search_enabled"] is True

    rv = client.get("/api/links/git")
    assert rv.status_code == 200
    assert rv.get_json()["link"]["search_enabled"] is True

    rv = client.get("/api/links/missing")
    assert rv.status_code == 404

    rv = client.delete("/api/links/git")
    assert rv.status_code == 200
    assert rv.get_json() == {"ok": True}

    rv = client.delete("/api/links/missing")
    assert rv.status_code == 404


def test_update_link_missing_returns_404(client):
    rv = client.put("/api/links/missing", json={"url": "https://example.com"})
    assert rv.status_code == 404


def test_update_link_validation_and_conflict(client):
    client.post("/api/links", json={"keyword": "a", "url": "https://a.com"})
    client.post("/api/links", json={"keyword": "b", "url": "https://b.com"})
    rv = client.put("/api/links/a", json={"url": "ftp://invalid"})
    assert rv.status_code == 400
    rv = client.put("/api/links/a", json={"keyword": "b", "url": "https://a.com"})
    assert rv.status_code == 400
    rv = client.put("/api/links/a", json={"keyword": "multi term", "url": "https://a.com"})
    assert rv.status_code == 400


def test_lists_crud_flow(client, db_conn):
    rv = client.post("/api/lists", json={"name": "Dev"})
    assert rv.status_code == 200
    assert rv.get_json() == {"ok": True}
    slug = db_conn.execute("SELECT slug FROM lists").fetchone()["slug"]
    assert slug == "dev"

    # Auto-created link exists
    row = db_conn.execute("SELECT url FROM links WHERE keyword=?", (slug,)).fetchone()
    assert f"/lists/{slug}" in row["url"]

    rv = client.get(f"/api/lists/{slug}")
    assert rv.status_code == 200
    assert rv.get_json()["list"]["name"] == "Dev"

    rv = client.patch(
        f"/api/lists/{slug}",
        json={"name": "Developers", "description": "desc"},
    )
    assert rv.status_code == 200
    assert rv.get_json()["list"]["name"] == "Developers"

    client.post("/api/links", json={"keyword": "gh", "url": "https://github.com"})
    rv = client.post(f"/api/lists/{slug}/links", json={"keyword": "gh"})
    assert rv.status_code == 200

    rv = client.get(f"/api/lists/{slug}/links")
    assert rv.status_code == 200
    assert rv.get_json()["links"][0]["keyword"] == "gh"

    rv = client.delete(f"/api/lists/{slug}/links/gh")
    assert rv.status_code == 200

    rv = client.delete(f"/api/lists/{slug}")
    assert rv.status_code == 200


def test_lists_validation_errors(client):
    rv = client.post("/api/lists", json={})
    assert rv.status_code == 400

    rv = client.post("/api/lists/dev/links", json={})
    assert rv.status_code == 404

    rv = client.get("/api/lists/missing")
    assert rv.status_code == 404


def test_lists_post_slug_generation_and_duplicate(client):
    rv = client.post("/api/lists", json={"slug": "slug-only"})
    assert rv.status_code == 200
    rv = client.post("/api/lists", json={"slug": "slug-only"})
    assert rv.status_code == 400


def test_lists_auto_link_conflict(client):
    client.post("/api/links", json={"keyword": "dev", "url": "https://example.com"})
    rv = client.post("/api/lists", json={"name": "Dev"})
    assert rv.status_code == 200


def test_lists_get_returns_entries(client):
    client.post("/api/lists", json={"name": "Dev"})
    rv = client.get("/api/lists")
    assert rv.status_code == 200
    assert rv.get_json()["lists"]


def test_list_detail_update_errors(client):
    client.post("/api/lists", json={"name": "Dev"})
    rv = client.put("/api/lists/dev", json={"slug": "dev2"})
    assert rv.status_code == 200

    client.post("/api/lists", json={"name": "Conflicting"})
    rv = client.put("/api/lists/dev2", json={"slug": "conflicting"})
    assert rv.status_code == 400


def test_list_detail_missing_returns_404(client):
    rv = client.put("/api/lists/missing", json={"slug": "x"})
    assert rv.status_code == 404


def test_list_links_error_paths(client):
    client.post("/api/lists", json={"name": "Dev"})
    rv = client.post("/api/lists/dev/links", json={"keyword": ""})
    assert rv.status_code == 400
    rv = client.post("/api/lists/dev/links", json={"keyword": "missing"})
    assert rv.status_code == 404

    rv = client.delete("/api/lists/dev/links/missing")
    assert rv.status_code == 404

    client.post("/api/links", json={"keyword": "gh", "url": "https://github.com"})
    rv = client.delete("/api/lists/missing/links/gh")
    assert rv.status_code == 404

    rv = client.get("/api/lists/ghost/links")
    assert rv.status_code == 404


def test_healthz_error_path(client, monkeypatch):
    def fail():
        raise RuntimeError("db down")

    monkeypatch.setattr(api, "get_db", fail)
    rv = client.get("/healthz")
    assert rv.status_code == 500
    assert rv.get_json()["status"] == "error"


def test_api_unexpected_error_returns_json(client, monkeypatch):
    def fail():
        raise RuntimeError("db down")

    monkeypatch.setattr(api, "get_db", fail)
    rv = client.get("/api/links")
    assert rv.status_code == 500
    assert rv.get_json() == {"error": "internal server error"}
