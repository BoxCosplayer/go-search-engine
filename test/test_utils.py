import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from backend.app import utils


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
        db_path="db.sqlite",
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


def test_ensure_config_file_exists_creates_from_template(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    template = tmp_path / "config-template.txt"
    template.write_text('{"host": "127.0.0.1"}', encoding="utf-8")

    def fake_discover():
        return cfg

    monkeypatch.setattr(utils, "_discover_config_path", fake_discover)
    assert utils._ensure_config_file_exists() == cfg
    assert json.loads(cfg.read_text(encoding="utf-8")) == {"host": "127.0.0.1"}


def test_ensure_config_file_handles_template_oserror(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    cfg = data_dir / "config.json"
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
    assert json.loads(created.read_text(encoding="utf-8")) == {"host": "127.0.0.1"}


def test_ensure_config_file_falls_back_to_defaults(monkeypatch, tmp_path):
    cfg = tmp_path / "data" / "config.json"
    monkeypatch.setattr(utils, "_discover_config_path", lambda: cfg)
    monkeypatch.setattr(utils, "runtime_base_dir", lambda: tmp_path)
    monkeypatch.setattr(utils, "_project_root", lambda: tmp_path)
    created = utils._ensure_config_file_exists()
    assert json.loads(created.read_text(encoding="utf-8")) == utils._DEFAULT_CONFIG


def test_discover_config_path_honors_env(monkeypatch, tmp_path):
    cfg = tmp_path / "nested" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GO_CONFIG_PATH", str(cfg))
    assert utils._discover_config_path() == cfg.resolve()


def test_discover_config_path_uses_exe_dir_when_frozen(monkeypatch, tmp_path):
    exe = tmp_path / "go.exe"
    exe.write_text("")
    monkeypatch.delenv("GO_CONFIG_PATH", raising=False)
    monkeypatch.setattr(utils.sys, "frozen", True, raising=False)
    monkeypatch.setattr(utils.sys, "executable", str(exe), raising=False)
    monkeypatch.setattr(utils, "_legacy_config_candidates", lambda _base: [])
    expected = exe.parent / "data" / "config.json"
    assert utils._discover_config_path() == expected.resolve()


def test_discover_config_path_prefers_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("GO_CONFIG_PATH", raising=False)
    monkeypatch.setattr(utils, "runtime_base_dir", lambda: tmp_path)
    monkeypatch.setattr(utils, "_legacy_config_candidates", lambda _base: [])
    assert utils._discover_config_path() == (tmp_path / "data" / "config.json")


def test_discover_config_path_falls_back_to_legacy(monkeypatch, tmp_path):
    monkeypatch.delenv("GO_CONFIG_PATH", raising=False)
    monkeypatch.setattr(utils, "runtime_base_dir", lambda: tmp_path)
    legacy = tmp_path / "config.json"
    legacy.write_text("{}", encoding="utf-8")
    assert utils._discover_config_path() == legacy.resolve()


def test_discover_config_path_returns_existing_data_cfg(monkeypatch, tmp_path):
    monkeypatch.delenv("GO_CONFIG_PATH", raising=False)
    monkeypatch.setattr(utils, "runtime_base_dir", lambda: tmp_path)
    data_cfg = tmp_path / "data" / "config.json"
    data_cfg.parent.mkdir(parents=True, exist_ok=True)
    data_cfg.write_text("{}", encoding="utf-8")
    assert utils._discover_config_path() == data_cfg.resolve()


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
    assert Path(loaded.db_path).parent == cfg.parent


def test_load_config_raises_for_invalid_json(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text("{ bad json", encoding="utf-8")
    monkeypatch.setattr(utils, "_discover_config_path", lambda: cfg)
    with pytest.raises(ValueError):
        utils.load_config()


def test_load_config_missing_file_creates_default(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(utils, "_discover_config_path", lambda: cfg)
    created = utils._ensure_config_file_exists()
    assert created.exists()
    data = json.loads(created.read_text(encoding="utf-8"))
    assert "db-path" in data


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
        db_path="db.sqlite",
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


def test_load_config_normalizes_relative_db_path(monkeypatch, tmp_path):
    cfg_dir = tmp_path / "data"
    cfg_dir.mkdir()
    cfg = cfg_dir / "config.json"
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
    assert loaded.db_path == str((cfg_dir / "links.db").resolve())


def test_normalize_db_path_handles_missing_model_copy(tmp_path):
    class DummyConfig:
        def __init__(self, db_path: str):
            self.db_path = db_path

    cfg = DummyConfig("links.db")
    cfg_path = tmp_path / "data" / "config.json"
    normalized = utils._normalize_db_path(cfg, cfg_path)
    assert normalized is cfg
    assert normalized.db_path == str((cfg_path.parent / "links.db").resolve())
