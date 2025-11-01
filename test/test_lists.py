def test_lists_index_renders(client, db_conn):
    db_conn.execute("INSERT INTO lists(slug, name, description) VALUES ('dev', 'Developers', 'desc')")
    db_conn.execute("INSERT INTO links(keyword, url, title) VALUES ('gh', 'https://github.com', 'GitHub')")
    db_conn.execute("INSERT INTO link_lists(link_id, list_id) VALUES (1, 1)")
    db_conn.commit()

    rv = client.get("/lists/")
    assert rv.status_code == 200
    assert b"Developers" in rv.data


def test_lists_view_shows_members(client, db_conn):
    db_conn.execute("INSERT INTO lists(slug, name) VALUES ('dev', 'Dev')")
    db_conn.execute("INSERT INTO links(keyword, url) VALUES ('gh', 'https://github.com')")
    db_conn.execute("INSERT INTO link_lists(link_id, list_id) VALUES (1, 1)")
    db_conn.commit()

    rv = client.get("/lists/dev")
    assert rv.status_code == 200
    assert b"github" in rv.data.lower()


def test_lists_view_missing_returns_404(client):
    rv = client.get("/lists/unknown")
    assert rv.status_code == 404
