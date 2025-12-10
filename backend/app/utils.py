import json
import logging
import os
import re
import shutil
import subprocess  # nosec B404
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

logger = logging.getLogger(__name__)


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


def get_db_path() -> Path:
    """Return the runtime database path, honoring GO_DB_PATH overrides."""
    override = os.environ.get("GO_DB_PATH")
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_absolute():
            candidate = runtime_base_dir() / candidate
        try:
            return candidate.resolve()
        except OSError:  # pragma: no cover - resolve can fail if drive missing
            return candidate
    return _default_db_path()


_DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 5000,
    "debug": False,
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
    roots = getattr(config, "file_allow", [])  # type: ignore[name-defined]

    if not roots:
        return False
    try:
        path = os.path.abspath(path)
        for root in roots:
            root_abs = os.path.abspath(str(root))
            if os.path.commonpath([path, root_abs]) == root_abs:
                return True
    except OSError as exc:
        logger.debug("Failed to evaluate allowed path", exc_info=exc)
    return False


def open_path_with_os(path: str) -> None:
    """Open a file/folder with the OS default handler (startfile/open/xdg-open)."""
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]  # nosec B606
    elif sys.platform == "darwin":
        opener = shutil.which("open")
        cmd = Path(opener).name if opener else "open"
        subprocess.Popen([cmd, path])  # nosec B603
    else:
        opener = shutil.which("xdg-open")
        cmd = Path(opener).name if opener else "xdg-open"
        subprocess.Popen([cmd, path])  # nosec B603


class GoConfig(BaseModel):
    """Application configuration validated by Pydantic."""

    host: str = "127.0.0.1"
    port: int = 5000
    debug: bool = False
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

    # Force debug to remain disabled in freshly generated configs.
    data["debug"] = False

    # Drop legacy db-path entries so newly generated configs don't expose it.
    data.pop("db-path", None)
    data.pop("db_path", None)

    payload = json.dumps(data, indent=4) + "\n"
    try:
        cfg_path.write_text(payload, encoding="utf-8")
    except OSError as exc:  # pragma: no cover - filesystem guard
        raise OSError(f"Failed to create default config: {exc}") from exc
    return cfg_path


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
    return loaded


# Importable, validated configuration object
config = load_config()
