import logging

from backend.app import logging_setup


def _restore_handlers(root, handlers):
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    for handler in handlers:
        root.addHandler(handler)


def test_configure_logging_writes_file(monkeypatch, tmp_path):
    log_file = tmp_path / "app.log"
    monkeypatch.setattr(logging_setup.utils, "get_log_path", lambda: log_file)
    monkeypatch.setattr(logging_setup.utils, "get_log_level", lambda: "INFO")

    root = logging.getLogger()
    original_handlers = list(root.handlers)
    try:
        logging_setup.configure_logging()
        logger = logging.getLogger("test.logger")
        logger.info("hello log")
        for handler in root.handlers:
            if hasattr(handler, "flush"):
                handler.flush()
        text = log_file.read_text(encoding="utf-8")
        assert "hello log" in text
    finally:
        _restore_handlers(root, original_handlers)


def test_configure_logging_invalid_level_and_file_error(monkeypatch, tmp_path):
    log_file = tmp_path / "logs" / "app.log"
    monkeypatch.setattr(logging_setup.utils, "get_log_path", lambda: log_file)
    monkeypatch.setattr(logging_setup.utils, "get_log_level", lambda: "nope")

    log_file.parent.write_text("not a dir", encoding="utf-8")

    root = logging.getLogger()
    original_handlers = list(root.handlers)
    try:
        logging_setup.configure_logging()
        assert all(type(handler).__name__ != "FileHandler" for handler in root.handlers)
    finally:
        _restore_handlers(root, original_handlers)


def test_resolve_log_level_blank_defaults_info():
    level, invalid = logging_setup._resolve_log_level("")
    assert level == logging.INFO
    assert invalid is False
