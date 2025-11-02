import json
import sqlite3

import pytest
from backend.app import utils


def prepare_test_config(monkeypatch, tmp_path):
    """Build and patch an isolated configuration environment."""
    db_file = tmp_path / "links.db"
    cfg_file = tmp_path / "config.json"
    cfg_data = {
        "host": "127.0.0.1",
        "port": 5001,
        "debug": True,
        "db-path": str(db_file),
        "allow-files": True,
        "fallback-url": "https://search.example/?q={q}",
        "file-allow": [str(tmp_path)],
    }
    cfg_file.write_text(json.dumps(cfg_data, indent=2), encoding="utf-8")

    config_obj = utils.GoConfig(**cfg_data)
    config_obj._config_path = cfg_file  # convenience for tests

    # Patch utils module state
    monkeypatch.setattr(utils, "config", config_obj, raising=False)
    monkeypatch.setattr(utils, "_discover_config_path", lambda: cfg_file)

    # Patch db module globals
    from backend.app import db as db_mod

    monkeypatch.setattr(db_mod, "config", config_obj, raising=False)
    monkeypatch.setattr(db_mod, "DB_PATH", config_obj.db_path, raising=False)
    monkeypatch.setattr(db_mod, "BASE_DIR", str(tmp_path), raising=False)

    # Patch main module globals
    from backend.app import main as main_mod

    monkeypatch.setattr(main_mod, "config", config_obj, raising=False)
    monkeypatch.setattr(main_mod, "HOST", config_obj.host, raising=False)
    monkeypatch.setattr(main_mod, "PORT", config_obj.port, raising=False)
    monkeypatch.setattr(main_mod, "DEBUG", config_obj.debug, raising=False)
    monkeypatch.setattr(main_mod, "FALLBACK_URL_TEMPLATE", config_obj.fallback_url, raising=False)
    monkeypatch.setattr(main_mod, "ALLOW_FILES", config_obj.allow_files, raising=False)
    monkeypatch.setattr(main_mod, "BASE_DIR", str(tmp_path), raising=False)

    def fake_resource_path(name: str) -> str:
        return str((tmp_path / name).resolve())

    monkeypatch.setattr(main_mod, "_resource_path", fake_resource_path, raising=False)

    # Patch admin helpers to reuse isolated config file
    from backend.app import admin as admin_mod
    from backend.app.admin import config_routes as admin_config_routes

    monkeypatch.setattr(admin_mod.utils, "config", config_obj, raising=False)
    monkeypatch.setattr(admin_mod, "_discover_config_path", lambda: cfg_file, raising=False)
    monkeypatch.setattr(admin_config_routes, "_discover_config_path", lambda: cfg_file, raising=False)

    return config_obj


@pytest.fixture()
def test_config(monkeypatch, tmp_path):
    """Isolate configuration and database per-test."""
    return prepare_test_config(monkeypatch, tmp_path)


@pytest.fixture()
def app_ctx(test_config):
    """Provide a Flask app context with initialized schema."""
    from backend.app.db import close_db, ensure_lists_schema, get_db, init_db
    from backend.app.main import app

    with app.app_context():
        init_db()
        ensure_lists_schema(get_db())
        yield app
        close_db(None)


@pytest.fixture()
def client(app_ctx):
    """Flask test client with isolated database."""
    return app_ctx.test_client()


@pytest.fixture()
def db_conn(test_config):
    """Direct sqlite3 connection to the isolated database."""
    conn = sqlite3.connect(test_config.db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()
