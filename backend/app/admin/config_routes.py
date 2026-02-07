import json

from flask import render_template, request

from .. import utils
from ..db import get_db
from ..logging_setup import configure_logging
from ..utils import GoConfig, _discover_config_path, load_config
from . import admin_bp


def _config_to_form_data(cfg: GoConfig) -> dict[str, object]:
    """Return form-friendly values for the config editor."""
    return {
        "host": cfg.host,
        "port": cfg.port,
        "debug": cfg.debug,
        "allow_files": cfg.allow_files,
        "fallback_url": cfg.fallback_url,
        "file_allow": "\n".join(cfg.file_allow),
        "admin_auth_enabled": cfg.admin_auth_enabled,
        "secret_key": cfg.secret_key,
        "log_level": cfg.log_level,
        "log_file": cfg.log_file,
    }


@admin_bp.route("/config", methods=["GET", "POST"])
def admin_config():
    """Display and update the application configuration."""
    load_error = ""
    try:
        current_cfg = load_config()
    except Exception as exc:  # pragma: no cover - defensive guard
        load_error = f"Failed to reload config: {exc}"
        current_cfg = utils.config

    form_values = _config_to_form_data(current_cfg)
    message = ""
    save_error = ""
    current_db_path = str(utils.get_db_path())
    current_log_path = str(utils.get_log_path())

    if request.method == "POST":
        host = (request.form.get("host") or "").strip()
        port_raw = (request.form.get("port") or "").strip()
        fallback_url = (request.form.get("fallback_url") or "").strip()
        file_allow_raw = request.form.get("file_allow") or ""
        file_allow_list = [line.strip() for line in file_allow_raw.splitlines() if line.strip()]
        secret_key = (request.form.get("secret_key") or "").strip()
        log_level = (request.form.get("log_level") or "").strip()
        log_file = (request.form.get("log_file") or "").strip()

        form_values = {
            "host": host or current_cfg.host,
            "port": port_raw or current_cfg.port,
            "debug": "debug" in request.form,
            "allow_files": "allow_files" in request.form,
            "fallback_url": fallback_url,
            "file_allow": file_allow_raw,
            "admin_auth_enabled": "admin_auth_enabled" in request.form,
            "secret_key": secret_key or current_cfg.secret_key,
            "log_level": log_level or current_cfg.log_level,
            "log_file": log_file,
        }

        if form_values["admin_auth_enabled"]:
            db = get_db()
            row = db.execute("SELECT COUNT(*) AS c FROM admin_users").fetchone()
            if not row or row["c"] == 0:
                save_error = (
                    "Create at least one admin user before enabling authentication. "
                    "Visit /admin/users to add a user."
                )

        payload = {
            "host": form_values["host"],
            "port": form_values["port"],
            "debug": form_values["debug"],
            "allow_files": form_values["allow_files"],
            "fallback_url": form_values["fallback_url"],
            "file_allow": file_allow_list,
            "admin_auth_enabled": form_values["admin_auth_enabled"],
            "secret_key": form_values["secret_key"],
            "log_level": form_values["log_level"],
            "log_file": form_values["log_file"],
        }

        if not save_error:
            try:
                new_cfg = GoConfig(**payload)
            except Exception as exc:  # pragma: no cover - surfaced to UI
                save_error = f"Unable to save configuration: {exc}"
            else:
                cfg_path = _discover_config_path()
                cfg_path.write_text(
                    json.dumps(new_cfg.model_dump(by_alias=True), indent=4) + "\n",
                    encoding="utf-8",
                )
                utils.config = new_cfg
                current_cfg = new_cfg
                form_values = _config_to_form_data(new_cfg)
                load_error = ""
                message = "Configuration saved."
                current_db_path = str(utils.get_db_path())
                current_log_path = str(utils.get_log_path())
                configure_logging()

    return render_template(
        "admin/config.html",
        form=form_values,
        load_error=load_error,
        save_error=save_error,
        message=message,
        db_path=current_db_path,
        log_path=current_log_path,
    )
