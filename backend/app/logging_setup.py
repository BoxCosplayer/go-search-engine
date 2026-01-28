from __future__ import annotations

import contextlib
import logging
import logging.config
from pathlib import Path

from . import utils


def _resolve_log_level(raw_level: str) -> tuple[int, bool]:
    """Return (level, invalid_flag)."""
    name = (raw_level or "").strip().upper()
    if not name:
        name = "INFO"
    level = logging.getLevelName(name)
    if isinstance(level, int):
        return level, False
    return logging.INFO, True


def _reset_root_handlers() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        with contextlib.suppress(Exception):
            handler.close()


def configure_logging() -> None:
    """Configure application logging to console + file."""
    raw_level = utils.get_log_level()
    level, invalid_level = _resolve_log_level(raw_level)

    log_path = utils.get_log_path()
    log_path = Path(log_path)

    handlers = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        }
    }
    root_handlers = ["console"]

    file_error: str | None = None
    if log_path:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handlers["file"] = {
                "class": "logging.FileHandler",
                "filename": str(log_path),
                "mode": "a",
                "encoding": "utf-8",
                "formatter": "default",
            }
            root_handlers.append("file")
        except OSError as exc:
            file_error = str(exc)

    _reset_root_handlers()
    logging.captureWarnings(True)
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
            },
            "handlers": handlers,
            "root": {"level": level, "handlers": root_handlers},
        }
    )

    if invalid_level:
        logging.getLogger(__name__).warning("Invalid log level '%s'; defaulting to INFO.", raw_level)

    if file_error:
        logging.getLogger(__name__).warning("Failed to initialize log file '%s': %s", log_path, file_error)
