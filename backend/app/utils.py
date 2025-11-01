import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, quote_plus, urlparse
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

_DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 5000,
    "debug": False,
    "db-path": "backend/app/data/links.db",
    "allow-files": True,
    "fallback-url": "",
    "file-allow": [],
}
_ARG_INDEX_RE = re.compile(r"\{(\d+)\}")
_TRAILING_PUNCT_RE = re.compile(r"[\s'\"`#@)\]\},.!?:;]+$")


def split_query(raw: str):
    """Split a raw query string into (keyword, remainder, words).

    Args:
        raw: The full input string (e.g., "gh issues open").

    Returns:
        tuple[str, str, list[str]]: (keyword, remainder, words)
    """
    parts = (raw or "").strip().split()
    if not parts:
        return "", "", []
    return parts[0], " ".join(parts[1:]), parts[1:]


def render_url_template(url_tmpl: str, full_q: str, args: str, words: list[str]) -> str:
    """Render a URL template by substituting supported placeholders.

    Supported placeholders: {q}, {args}, {args_raw}, {args_url}, and {1},{2},...
    """
    out = (
        url_tmpl.replace("{q}", quote_plus(full_q))
        .replace("{args}", quote_plus(args))
        .replace("{args_raw}", args)
        .replace("{args_url}", quote(args, safe=""))
    )

    def _repl(m):
        i = int(m.group(1)) - 1
        return quote_plus(words[i]) if 0 <= i < len(words) else ""

    return _ARG_INDEX_RE.sub(_repl, out)


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
        # Build UNC path: \\server\share\path using f-string
        path = f"\\\\{u.netloc}{path.replace('/', '\\')}"
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
    db_path: str = Field("backend/app/data/links.db", alias="db-path")
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


def _discover_config_path() -> Path:
    """Return absolute path to the project-root config.json.

    Assumes config.json is always located at the repository root
    (two directories above this file).
    """
    return Path(__file__).resolve().parents[2] / "config.json"


def _ensure_config_file_exists() -> Path:
    """Ensure config.json is present, creating an example if missing."""

    cfg_path = _discover_config_path()
    if cfg_path.exists():
        return cfg_path

    template_path = cfg_path.with_name("config-template.txt")
    try:
        if template_path.exists():
            contents = template_path.read_text(encoding="utf-8")
        else:
            contents = json.dumps(_DEFAULT_CONFIG, indent=4) + "\n"
        cfg_path.write_text(contents, encoding="utf-8")
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
        return GoConfig(**data)
    except ValidationError as e:
        raise ValueError(f"Invalid configuration: {e}") from e


# Importable, validated configuration object
config = load_config()
