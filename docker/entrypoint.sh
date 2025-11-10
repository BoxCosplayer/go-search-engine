#!/usr/bin/env bash
set -euo pipefail

APP_HOME="${APP_HOME:-/app}"
export GO_CONFIG_PATH="${GO_CONFIG_PATH:-/data/config.json}"
export GO_DB_PATH="${GO_DB_PATH:-/data/links.db}"
export GO_HOST="${GO_HOST:-127.0.0.1}"
export GO_PORT="${GO_PORT:-5000}"
export GO_GUNICORN_WORKERS="${GO_GUNICORN_WORKERS:-2}"
export GO_GUNICORN_TIMEOUT="${GO_GUNICORN_TIMEOUT:-60}"
export GO_APP_MODULE="${GO_APP_MODULE:-backend.wsgi:application}"
export GO_CONFIG_TEMPLATE="${GO_CONFIG_TEMPLATE:-${APP_HOME}/config-template.txt}"

ensure_config_file() {
    local config_dir
    config_dir="$(dirname "$GO_CONFIG_PATH")"
    mkdir -p "$config_dir"
    if [[ -f "$GO_CONFIG_PATH" ]]; then
        return
    fi

    if [[ -f "$GO_CONFIG_TEMPLATE" ]]; then
        cp "$GO_CONFIG_TEMPLATE" "$GO_CONFIG_PATH"
        return
    fi

    cat >"$GO_CONFIG_PATH" <<'JSON'
{
  "host": "127.0.0.1",
  "port": 5000,
  "debug": false,
  "db-path": "/data/links.db",
  "allow-files": false,
  "fallback-url": "",
  "file-allow": []
}
JSON
}

patch_config() {
    /usr/local/bin/python <<'PY'
import json
import os
import pathlib

config_path = pathlib.Path(os.environ["GO_CONFIG_PATH"])
config_path.parent.mkdir(parents=True, exist_ok=True)
try:
    data = json.loads(config_path.read_text(encoding="utf-8"))
except Exception:
    data = {}

def ensure(key, default):
    value = data.get(key)
    if value in (None, "", "127.0.0.1"):
        data[key] = default

ensure("host", os.environ["GO_HOST"])
ensure("port", int(os.environ["GO_PORT"]))

db_path = data.get("db-path")
if not db_path or db_path in ("backend/app/data/links.db", "links.db"):
    data["db-path"] = os.environ["GO_DB_PATH"]

file_allow = data.get("file-allow")
if not isinstance(file_allow, list):
    data["file-allow"] = []

config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
PY
}

ensure_db_directory() {
    local db_dir
    db_dir="$(dirname "$GO_DB_PATH")"
    mkdir -p "$db_dir"
}

ensure_config_file
patch_config
ensure_db_directory

if [[ $# -gt 0 ]]; then
    exec "$@"
fi

IFS=' ' read -r -a EXTRA_ARGS <<<"${GO_GUNICORN_EXTRA_ARGS:-}"

cmd=(
    gunicorn
    "--workers" "$GO_GUNICORN_WORKERS"
    "--bind" "${GO_HOST}:${GO_PORT}"
    "--timeout" "$GO_GUNICORN_TIMEOUT"
)

if [[ ${#EXTRA_ARGS[@]} -gt 0 && -n "${EXTRA_ARGS[*]// }" ]]; then
    cmd+=("${EXTRA_ARGS[@]}")
fi

cmd+=("$GO_APP_MODULE")

exec "${cmd[@]}"
