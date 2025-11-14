import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from backend.app import utils


@pytest.fixture
def fake_user_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "appdata"
    monkeypatch.setattr(utils, "_user_data_dir", lambda: data_dir)
    return data_dir


@pytest.fixture
def fake_db_default(fake_user_data_dir, monkeypatch):
    target = fake_user_data_dir / "links.db"
    monkeypatch.setattr(utils, "_default_db_path", lambda: target)
    return target


def test_default_db_path_windows_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(utils.sys, "platform", "win32", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(utils.Path, "home", lambda: tmp_path)
    expected = tmp_path / "AppData" / "Roaming" / "go-search-engine" / "links.db"
    assert utils._default_db_path() == expected


def test_default_db_path_darwin(monkeypatch, tmp_path):
    monkeypatch.setattr(utils.sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(utils.Path, "home", lambda: tmp_path)
    expected = tmp_path / "Library" / "Application Support" / "go-search-engine" / "links.db"
    assert utils._default_db_path() == expected


def test_default_db_path_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(utils.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(utils.Path, "home", lambda: tmp_path)
    expected = tmp_path / ".local" / "share" / "go-search-engine" / "links.db"
    assert utils._default_db_path() == expected


def test_get_db_path_defaults_to_user_dir(monkeypatch, fake_db_default):
    monkeypatch.delenv("GO_DB_PATH", raising=False)
    assert utils.get_db_path() == fake_db_default


def test_get_db_path_honors_absolute_env(monkeypatch, tmp_path):
    target = tmp_path / "custom" / "links.db"
    monkeypatch.setenv("GO_DB_PATH", str(target))
    assert utils.get_db_path() == target.resolve()


def test_get_db_path_resolves_relative_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GO_DB_PATH", "data/links.db")
    monkeypatch.setattr(utils, "runtime_base_dir", lambda: tmp_path)
    expected = (tmp_path / "data" / "links.db").resolve()
    assert utils.get_db_path() == expected


def test_sanitize_query_normalizes_quotes_and_trailing_chars():
    assert utils.sanitize_query('"Hello?! "') == "Hello"
    assert utils.sanitize_query("' spaced '") == "spaced"
    assert utils.sanitize_query("") == ""


def test_to_slug_prefers_slugify(monkeypatch):
    calls = {}

    def fake_slugify(value, separator="-", lowercase=True):
        calls["value"] = value
        calls["separator"] = separator
        calls["lowercase"] = lowercase
        return "custom-output"

    monkeypatch.setattr(utils, "slugify", fake_slugify)
    assert utils.to_slug("Hello World!") == "custom-output"
    assert calls == {"value": "Hello World!", "separator": "-", "lowercase": True}


def test_to_slug_legacy_slugify(monkeypatch):
    def legacy_slugify(value, *_, **kwargs):
        if kwargs:
            raise TypeError("legacy")
        return value.replace(" ", "_")

    monkeypatch.setattr(utils, "slugify", legacy_slugify)
    assert utils.to_slug("Mixed Case Value") == "mixed_case_value"


def test_to_slug_without_slugify(monkeypatch):
    monkeypatch.setattr(utils, "slugify", None)
    assert utils.to_slug("Hello, World!") == "hello-world"


def test_file_url_to_path_handles_local_and_unc(tmp_path, monkeypatch):
    file_path = tmp_path / "file.txt"
    url = file_path.as_uri()
    assert utils.file_url_to_path(url) == os.path.normpath(str(file_path))

    # Force windows style UNC conversion
    monkeypatch.setattr(utils, "url2pathname", lambda p: p.replace("/", "\\"))
    unc = utils.file_url_to_path("file://server/shared/path/to/file")
    assert unc.startswith("\\\\server")


def test_is_allowed_path_respects_configuration(monkeypatch):
    allow_root = Path("/allowed").resolve()
    deny_root = Path("/denied").resolve()
    cfg = utils.GoConfig(
        host="127.0.0.1",
        port=5000,
        debug=False,
        allow_files=True,
        fallback_url="",
        file_allow=[str(allow_root)],
    )
    monkeypatch.setattr(utils, "config", cfg, raising=False)
    assert utils.is_allowed_path(str(allow_root / "file.txt"))
    assert not utils.is_allowed_path(str(deny_root / "file.txt"))

    cfg_empty = cfg.model_copy(update={"file_allow": []})
    monkeypatch.setattr(utils, "config", cfg_empty, raising=False)
    assert utils.is_allowed_path(str(allow_root / "file.txt")) is False


def test_open_path_with_os_windows(monkeypatch):
    captured = []
    monkeypatch.setattr(utils.sys, "platform", "win32", raising=False)
    monkeypatch.setattr(os, "startfile", lambda path: captured.append(path), raising=False)
    utils.open_path_with_os("C:\\demo.txt")
    assert captured == ["C:\\demo.txt"]


def test_open_path_with_os_darwin(monkeypatch):
    captured = []
    monkeypatch.setattr(utils.sys, "platform", "darwin", raising=False)

    def fake_popen(cmd):
        captured.append(cmd)
        return SimpleNamespace()

    monkeypatch.setattr(utils.subprocess, "Popen", fake_popen)
    utils.open_path_with_os("/tmp/demo.txt")
    assert captured == [["open", "/tmp/demo.txt"]]


def test_open_path_with_os_linux(monkeypatch):
    captured = []
    monkeypatch.setattr(utils.sys, "platform", "linux", raising=False)

    def fake_popen(cmd):
        captured.append(cmd)
        return SimpleNamespace()

    monkeypatch.setattr(utils.subprocess, "Popen", fake_popen)
    utils.open_path_with_os("/tmp/demo.txt")
    assert captured == [["xdg-open", "/tmp/demo.txt"]]


def test_ensure_config_file_exists_creates_from_template(tmp_path, monkeypatch, fake_db_default):
    cfg = tmp_path / "config.json"
    template = tmp_path / "config-template.txt"
    template.write_text('{"host": "127.0.0.1"}', encoding="utf-8")

    def fake_discover():
        return cfg

    monkeypatch.setattr(utils, "_discover_config_path", fake_discover)
    assert utils._ensure_config_file_exists() == cfg
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["host"] == "127.0.0.1"
    assert "db-path" not in data
    assert "db_path" not in data
    assert data["debug"] is False


def test_ensure_config_file_handles_template_oserror(monkeypatch, tmp_path, fake_db_default):
    cfg_dir = tmp_path / "cfgdir"
    cfg = cfg_dir / "config.json"
    template = tmp_path / "config-template.txt"
    template.write_text('{"host": "127.0.0.1"}', encoding="utf-8")

    monkeypatch.setattr(utils, "_discover_config_path", lambda: cfg)
    monkeypatch.setattr(utils, "runtime_base_dir", lambda: tmp_path)
    monkeypatch.setattr(utils, "_project_root", lambda: tmp_path)

    original_exists = utils.Path.exists

    def fake_exists(path_self):
        if path_self == cfg.with_name("config-template.txt"):
            raise OSError("boom")
        return original_exists(path_self)

    monkeypatch.setattr(utils.Path, "exists", fake_exists)
    created = utils._ensure_config_file_exists()
    data = json.loads(created.read_text(encoding="utf-8"))
    assert data["host"] == "127.0.0.1"
    assert "db-path" not in data
    assert data["debug"] is False


def test_ensure_config_file_falls_back_to_defaults(monkeypatch, tmp_path, fake_db_default):
    cfg = tmp_path / "cfgdir" / "config.json"
    monkeypatch.setattr(utils, "_discover_config_path", lambda: cfg)
    monkeypatch.setattr(utils, "runtime_base_dir", lambda: tmp_path)
    monkeypatch.setattr(utils, "_project_root", lambda: tmp_path)
    created = utils._ensure_config_file_exists()
    assert json.loads(created.read_text(encoding="utf-8")) == utils._DEFAULT_CONFIG


def test_ensure_config_file_strips_custom_db_path(monkeypatch, tmp_path, fake_db_default):
    cfg = tmp_path / "config.json"
    template = tmp_path / "config-template.txt"
    template.write_text('{"db-path": "/custom/location/links.db"}', encoding="utf-8")
    monkeypatch.setattr(utils, "_discover_config_path", lambda: cfg)
    created = utils._ensure_config_file_exists()
    data = json.loads(created.read_text(encoding="utf-8"))
    assert "db-path" not in data


def test_ensure_config_file_forces_debug_false(monkeypatch, tmp_path, fake_db_default):
    cfg = tmp_path / "config.json"
    template = tmp_path / "config-template.txt"
    template.write_text('{"debug": true}', encoding="utf-8")
    monkeypatch.setattr(utils, "_discover_config_path", lambda: cfg)
    created = utils._ensure_config_file_exists()
    data = json.loads(created.read_text(encoding="utf-8"))
    assert data["debug"] is False


def test_ensure_config_file_handles_non_object_template(monkeypatch, tmp_path, fake_db_default):
    cfg = tmp_path / "config.json"
    template = tmp_path / "config-template.txt"
    template.write_text('["not", "an", "object"]', encoding="utf-8")
    monkeypatch.setattr(utils, "_discover_config_path", lambda: cfg)
    created = utils._ensure_config_file_exists()
    data = json.loads(created.read_text(encoding="utf-8"))
    assert data == utils._DEFAULT_CONFIG


def test_discover_config_path_honors_env(monkeypatch, tmp_path):
    cfg = tmp_path / "nested" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GO_CONFIG_PATH", str(cfg))
    assert utils._discover_config_path() == cfg.resolve()


def test_discover_config_path_defaults_to_user_dir(monkeypatch, fake_user_data_dir):
    monkeypatch.delenv("GO_CONFIG_PATH", raising=False)
    monkeypatch.setattr(utils, "_legacy_config_candidates", lambda _base: [])
    expected = fake_user_data_dir / "config.json"
    assert utils._discover_config_path() == expected.resolve()


def test_discover_config_path_uses_user_dir_when_frozen(monkeypatch, fake_user_data_dir, tmp_path):
    exe = tmp_path / "go.exe"
    exe.write_text("")
    monkeypatch.delenv("GO_CONFIG_PATH", raising=False)
    monkeypatch.setattr(utils.sys, "frozen", True, raising=False)
    monkeypatch.setattr(utils.sys, "executable", str(exe), raising=False)
    monkeypatch.setattr(utils, "_legacy_config_candidates", lambda _base: [])
    expected = fake_user_data_dir / "config.json"
    assert utils._discover_config_path() == expected.resolve()


def test_discover_config_path_prefers_legacy_when_present(monkeypatch, tmp_path, fake_user_data_dir):
    monkeypatch.delenv("GO_CONFIG_PATH", raising=False)
    legacy_base = tmp_path / "legacy"
    legacy_base.mkdir()
    legacy_cfg = legacy_base / "data" / "config.json"
    legacy_cfg.parent.mkdir(parents=True, exist_ok=True)
    legacy_cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(utils, "runtime_base_dir", lambda: legacy_base)
    target = utils._discover_config_path()
    assert target == (fake_user_data_dir / "config.json")
    assert target.exists()
    assert target.read_text(encoding="utf-8") == legacy_cfg.read_text(encoding="utf-8")


def test_discover_config_path_falls_back_when_copy_fails(monkeypatch, tmp_path, fake_user_data_dir):
    monkeypatch.delenv("GO_CONFIG_PATH", raising=False)
    legacy_base = tmp_path / "legacy"
    legacy_base.mkdir()
    legacy_cfg = legacy_base / "config.json"
    legacy_cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(utils, "runtime_base_dir", lambda: legacy_base)
    default_cfg = fake_user_data_dir / "config.json"
    original_write = utils.Path.write_text

    def fake_write(self, *args, **kwargs):
        if self == default_cfg:
            raise OSError("boom")
        return original_write(self, *args, **kwargs)

    monkeypatch.setattr(utils.Path, "write_text", fake_write, raising=False)
    fake_write(tmp_path / "other.json", "{}", encoding="utf-8")
    target = utils._discover_config_path()
    assert target == legacy_cfg.resolve()


def test_discover_config_path_returns_existing_user_config(monkeypatch, fake_user_data_dir):
    monkeypatch.delenv("GO_CONFIG_PATH", raising=False)
    cfg = fake_user_data_dir / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("{}", encoding="utf-8")
    assert utils._discover_config_path() == cfg.resolve()


def test_load_config_validates_json(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "host": "127.0.0.1",
                "port": 4000,
                "debug": False,
                "db-path": "db.sqlite",
                "allow-files": False,
                "fallback-url": "",
                "file-allow": [],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(utils, "_discover_config_path", lambda: cfg)
    loaded = utils.load_config()
    assert loaded.port == 4000
    assert loaded.allow_files is False
    assert not hasattr(loaded, "db_path")


def test_load_config_raises_for_invalid_json(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text("{ bad json", encoding="utf-8")
    monkeypatch.setattr(utils, "_discover_config_path", lambda: cfg)
    with pytest.raises(ValueError):
        utils.load_config()


def test_load_config_missing_file_creates_default(tmp_path, monkeypatch, fake_db_default):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(utils, "_discover_config_path", lambda: cfg)
    created = utils._ensure_config_file_exists()
    assert created.exists()
    data = json.loads(created.read_text(encoding="utf-8"))
    assert "db-path" not in data


def test_ensure_config_file_handles_invalid_template(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    template = cfg.with_name("config-template.txt")
    template.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(utils, "_discover_config_path", lambda: cfg)
    created = utils._ensure_config_file_exists()
    payload = json.loads(created.read_text(encoding="utf-8"))
    assert payload["host"] == utils._DEFAULT_CONFIG["host"]
    assert payload.get("file-allow") == utils._DEFAULT_CONFIG["file-allow"]


def test_load_config_ignores_legacy_db_path(monkeypatch, tmp_path, fake_db_default):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "host": "127.0.0.1",
                "port": 5000,
                "debug": False,
                "db-path": "links.db",
                "allow-files": False,
                "fallback-url": "",
                "file-allow": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(utils, "_discover_config_path", lambda: cfg)
    loaded = utils.load_config()
    assert loaded.host == "127.0.0.1"
    assert not hasattr(loaded, "db_path")


def test_to_slug_general_exception(monkeypatch):
    def problematic_slugify(value, *_, **kwargs):
        if kwargs:
            raise TypeError("legacy")
        raise Exception("boom")

    monkeypatch.setattr(utils, "slugify", problematic_slugify)
    assert utils.to_slug("Hello There!") == "hello-there"


def test_file_url_to_path_requires_file_scheme():
    with pytest.raises(ValueError):
        utils.file_url_to_path("https://example.com")


def test_is_allowed_path_handles_exceptions(monkeypatch):
    cfg = utils.GoConfig(
        host="127.0.0.1",
        port=5000,
        debug=False,
        allow_files=True,
        fallback_url="",
        file_allow=["/tmp"],
    )
    monkeypatch.setattr(utils, "config", cfg, raising=False)

    def bad_abspath(_):
        raise OSError("boom")

    monkeypatch.setattr(utils.os.path, "abspath", bad_abspath)
    assert utils.is_allowed_path("/tmp/file") is False


def test_load_config_file_missing_error(monkeypatch, tmp_path):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(utils, "_ensure_config_file_exists", lambda: missing)
    with pytest.raises(FileNotFoundError):
        utils.load_config()


def test_load_config_validation_error(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "host": "127.0.0.1",
                "port": "not-a-number",
                "debug": False,
                "db-path": "db.sqlite",
                "allow-files": False,
                "fallback-url": "",
                "file-allow": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(utils, "_discover_config_path", lambda: cfg)
    with pytest.raises(ValueError):
        utils.load_config()
