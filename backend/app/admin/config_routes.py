import json

from flask import render_template, request

from .. import utils
from ..utils import GoConfig, _discover_config_path, load_config
from . import admin_bp


def _config_to_form_data(cfg: GoConfig) -> dict[str, object]:
    """Return form-friendly values for the config editor."""
    return {
        "host": cfg.host,
        "port": cfg.port,
        "debug": cfg.debug,
        "db_path": cfg.db_path,
        "allow_files": cfg.allow_files,
        "fallback_url": cfg.fallback_url,
        "file_allow": "\n".join(cfg.file_allow),
        "run_on_startup": cfg.run_on_startup,
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

    if request.method == "POST":
        host = (request.form.get("host") or "").strip()
        port_raw = (request.form.get("port") or "").strip()
        db_path = (request.form.get("db_path") or "").strip()
        fallback_url = (request.form.get("fallback_url") or "").strip()
        file_allow_raw = request.form.get("file_allow") or ""
        file_allow_list = [line.strip() for line in file_allow_raw.splitlines() if line.strip()]

        form_values = {
            "host": host or current_cfg.host,
            "port": port_raw or current_cfg.port,
            "debug": "debug" in request.form,
            "db_path": db_path or current_cfg.db_path,
            "allow_files": "allow_files" in request.form,
            "fallback_url": fallback_url,
            "file_allow": file_allow_raw,
            "run_on_startup": "run_on_startup" in request.form,
        }

        payload = {
            "host": form_values["host"],
            "port": form_values["port"],
            "debug": form_values["debug"],
            "db_path": form_values["db_path"],
            "allow_files": form_values["allow_files"],
            "fallback_url": form_values["fallback_url"],
            "file_allow": file_allow_list,
            "run_on_startup": form_values["run_on_startup"],
        }

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
            message = "Configuration saved."
            load_error = ""

    return render_template(
        "admin/config.html",
        form=form_values,
        load_error=load_error,
        save_error=save_error,
        message=message,
    )
