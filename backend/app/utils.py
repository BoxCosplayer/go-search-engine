import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

try:
    from pydantic import BaseModel, Field, ValidationError

    try:
        from pydantic import ConfigDict  # v2
    except Exception:  # pragma: no cover
        ConfigDict = None  # type: ignore
except Exception:  # pragma: no cover
    BaseModel = object  # type: ignore

    def Field(*a, **k):  # type: ignore
        return None

    ValidationError = Exception  # type: ignore
    ConfigDict = None  # type: ignore

try:
    # Provided by the python-slugify package
    from slugify import slugify  # type: ignore
except ImportError:  # pragma: no cover
    slugify = None  # type: ignore


def runtime_base_dir() -> Path:
    """Return the folder where runtime artifacts should live."""
    if getattr(sys, "frozen", False):
        exe = Path(getattr(sys, "executable", __file__)).resolve()
        return exe.parent
    return Path(__file__).resolve().parent


def _project_root() -> Path:
    """Best-effort project root for dev environments."""
    return Path(__file__).resolve().parents[2]


_APP_DIR_NAME = "go-search-engine"


def _user_data_dir() -> Path:
    """Return the OS-specific user data directory for this app."""
    if sys.platform.startswith("win"):
        root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if root:
            return Path(root) / _APP_DIR_NAME
        return Path.home() / "AppData" / "Roaming" / _APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_DIR_NAME
    return Path.home() / ".local" / "share" / _APP_DIR_NAME


def _default_db_path() -> Path:
    """Return the OS-specific default location for links.db."""
    return _user_data_dir() / "links.db"


def _default_config_path() -> Path:
    """Return the OS-specific default location for config.json."""
    return _user_data_dir() / "config.json"


def _normalize_db_token(value: str) -> str:
    return value.replace("\\", "/").strip().lower()


def _legacy_absolute_paths() -> set[str]:
    """Return normalized absolute paths for historical defaults."""
    roots = set()
    candidates = [
        _project_root() / "backend" / "app" / "data" / "links.db",
        _project_root() / "data" / "links.db",
    ]
    for candidate in candidates:
        try:
            roots.add(_normalize_db_token(str(candidate.resolve())))
        except OSError:
            roots.add(_normalize_db_token(str(candidate)))
    return roots


_LEGACY_DB_SENTINELS = {
    "links.db",
    "data/links.db",
    "backend/app/data/links.db",
    "{appdata}/go-search-engine/links.db",
    "%appdata%/go-search-engine/links.db",
}
_LEGACY_DB_ABSOLUTE_SENTINELS = _legacy_absolute_paths()


_DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 5000,
    "debug": False,
    "db-path": str(_default_db_path()),
    "allow-files": True,
    "fallback-url": "",
    "file-allow": [],
}
_TRAILING_PUNCT_RE = re.compile(r"[\s'\"`#@)\]\},.!?:;]+$")


def sanitize_query(raw: str) -> str:
    """Normalize an incoming query string: trim, unquote, strip trailing punct."""
    if not raw:
        return ""
    q = raw.strip()
    if (len(q) >= 2) and ((q[0], q[-1]) in {('"', '"'), ("'", "'"), ("`", "`")}):
        q = q[1:-1].strip()
    return _TRAILING_PUNCT_RE.sub("", q)


def to_slug(s: str) -> str:
    """Return a URL-friendly slug.

    Prefers python-slugify if available. If an older 'slugify' package is
    installed (different API), gracefully falls back and normalizes output.
    """
    txt = (s or "").strip()
    if slugify is not None:
        try:
            # python-slugify API
            return slugify(txt, separator="-", lowercase=True)  # type: ignore[arg-type]
        except TypeError:
            # Older 'slugify' package without these kwargs
            try:
                res = slugify(txt)  # type: ignore[call-arg]
            except Exception:
                res = txt
            res = res.replace(" ", "-").lower()
            return re.sub(r"[^a-z0-9\-_]", "", res)
    # Pure-Python fallback
    txt = txt.lower()
    txt = re.sub(r"\s+", "-", txt)
    return re.sub(r"[^a-z0-9\-_]", "", txt)


def file_url_to_path(url: str) -> str:
    """Convert a file:// URL to a local OS path (handles UNC on Windows)."""
    u = urlparse(url)
    if u.scheme != "file":
        raise ValueError("not a file URL")
    path = url2pathname(u.path or "")
    if u.netloc and u.netloc.lower() not in ("", "localhost"):
        # Build UNC path: \\server\share\path using a safely escaped backslash
        unc_path = path.replace("/", "\\")
        path = f"\\\\{u.netloc}{unc_path}"
    return os.path.normpath(path)


def is_allowed_path(path: str) -> bool:
    """Return True if path is within any configured allowed root.

    Uses config.file_allow (list of absolute directories). If empty, allow all paths.
    """
    roots: list[str] = []
    # try:
    #     roots = getattr(config, "file_allow", [])  # type: ignore[name-defined]
    # except Exception:
    #     pass

    roots = getattr(config, "file_allow", [])  # type: ignore[name-defined]

    if not roots:
        return False
    try:
        path = os.path.abspath(path)
        for root in roots:
            root_abs = os.path.abspath(str(root))
            if os.path.commonpath([path, root_abs]) == root_abs:
                return True
    except Exception:
        pass
    return False


def open_path_with_os(path: str) -> None:
    """Open a file/folder with the OS default handler (startfile/open/xdg-open)."""
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class GoConfig(BaseModel):
    """Application configuration validated by Pydantic."""

    host: str = "127.0.0.1"
    port: int = 5000
    debug: bool = False
    db_path: str = Field("links.db", alias="db-path")
    allow_files: bool = Field(False, alias="allow-files")
    fallback_url: str = Field("", alias="fallback-url")
    file_allow: list[str] = Field(default_factory=list, alias="file-allow")

    # Pydantic v2 config if available; fallback to v1
    if ConfigDict:
        model_config = ConfigDict(populate_by_name=True, extra="ignore")  # type: ignore[assignment]
    else:  # type: ignore[no-redef]

        class Config:  # type: ignore[override]  # pragma: no cover
            allow_population_by_field_name = True  # pragma: no cover
            extra = "ignore"  # pragma: no cover


def _legacy_config_candidates(base_dir: Path) -> list[Path]:
    """Return historical config paths that should remain readable."""
    return [
        base_dir / "data" / "config.json",
        base_dir / "config.json",
        base_dir.parent / "config.json",
        _project_root() / "config.json",
    ]


def _should_replace_db_path(raw: str, cfg_path: Path | None = None) -> bool:
    """Return True when db-path should be upgraded to the AppData default."""

    if not raw:
        return True

    normalized = _normalize_db_token(str(raw))
    if normalized in _LEGACY_DB_SENTINELS or normalized in _LEGACY_DB_ABSOLUTE_SENTINELS:
        return True

    try:
        absolute_norm = _normalize_db_token(str(Path(raw).expanduser().resolve()))
    except OSError:
        absolute_norm = ""
    if absolute_norm in _LEGACY_DB_ABSOLUTE_SENTINELS:
        return True

    if cfg_path is not None:
        candidates = [
            cfg_path.parent / "links.db",
            cfg_path.parent / "data" / "links.db",
        ]
        for candidate in candidates:
            try:
                cand_norm = _normalize_db_token(str(candidate.resolve()))
            except OSError:
                cand_norm = _normalize_db_token(str(candidate))
            if normalized == cand_norm or absolute_norm == cand_norm:
                return True

    return False


def _discover_config_path() -> Path:
    """Return absolute path to config.json, honoring GO_CONFIG_PATH overrides."""
    override = os.environ.get("GO_CONFIG_PATH")
    if override:
        return Path(override).expanduser()

    default_cfg = _default_config_path()
    if default_cfg.exists():
        return default_cfg

    default_cfg.parent.mkdir(parents=True, exist_ok=True)

    base_dir = runtime_base_dir()

    for candidate in _legacy_config_candidates(base_dir):
        if candidate.exists():
            try:
                contents = candidate.read_text(encoding="utf-8")
                default_cfg.write_text(contents, encoding="utf-8")
                return default_cfg
            except OSError:
                return candidate

    return default_cfg


def _ensure_config_file_exists() -> Path:
    """Ensure config.json is present, creating an example if missing."""

    cfg_path = _discover_config_path()
    if cfg_path.exists():
        return cfg_path

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    template_candidates = [
        cfg_path.with_name("config-template.txt"),
        runtime_base_dir() / "config-template.txt",
        _project_root() / "config-template.txt",
    ]
    contents = None
    for tpl in template_candidates:
        try:
            if tpl.exists():
                contents = tpl.read_text(encoding="utf-8")
                break
        except OSError:
            continue

    if contents is None:
        data = dict(_DEFAULT_CONFIG)
    else:
        try:
            parsed = json.loads(contents)
            if not isinstance(parsed, dict):
                raise ValueError("template is not a JSON object")
        except (json.JSONDecodeError, ValueError):
            parsed = {}
        data = dict(_DEFAULT_CONFIG)
        data.update(parsed)

    current_db_path = str(data.get("db-path", "")).strip()
    if _should_replace_db_path(current_db_path, cfg_path):
        data["db-path"] = str(_default_db_path())

    payload = json.dumps(data, indent=4) + "\n"
    try:
        cfg_path.write_text(payload, encoding="utf-8")
    except OSError as exc:  # pragma: no cover - filesystem guard
        raise OSError(f"Failed to create default config: {exc}") from exc
    return cfg_path


def _normalize_db_path(cfg: GoConfig, cfg_path: Path) -> GoConfig:
    """Ensure db_path is absolute, rooting relative paths next to config."""

    db_value = str(cfg.db_path)
    if _should_replace_db_path(db_value, cfg_path):
        raw = _default_db_path()
    else:
        raw_path = Path(db_value).expanduser()
        raw = (cfg_path.parent / raw_path).resolve() if not raw_path.is_absolute() else raw_path.resolve()

    updated = str(raw)
    if hasattr(cfg, "model_copy"):
        return cfg.model_copy(update={"db_path": updated})  # type: ignore[attr-defined]
    cfg.db_path = updated  # type: ignore[attr-defined]
    return cfg


def load_config() -> GoConfig:
    """Load and validate config.json using Pydantic."""
    cfg_path = _ensure_config_file_exists()
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Config file not found: {cfg_path}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {cfg_path}: {e}") from e
    try:
        loaded = GoConfig(**data)
    except ValidationError as e:
        raise ValueError(f"Invalid configuration: {e}") from e
    return _normalize_db_path(loaded, cfg_path)


# Importable, validated configuration object
config = load_config()
