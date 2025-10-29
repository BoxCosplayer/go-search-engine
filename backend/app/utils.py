import os
import re
import subprocess
import sys
from urllib.parse import quote, quote_plus, urlparse
from urllib.request import url2pathname

try:
    # Provided by the python-slugify package
    from slugify import slugify  # type: ignore
except ImportError:  # pragma: no cover
    slugify = None  # type: ignore


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
    """Return True if path is within any GO_FILE_ALLOW root (or allowed by default)."""
    allow_env = os.environ.get("GO_FILE_ALLOW", "").strip()
    if not allow_env:
        return True
    roots = [p for p in (x.strip() for x in allow_env.split(";")) if p]
    try:
        path = os.path.abspath(path)
        for root in roots:
            root = os.path.abspath(root)
            if os.path.commonpath([path, root]) == root:
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


def load_config():
    """Load JSON config from GO_CONFIG_PATH or repo config.json (best-effort)."""
    cfg_path = os.environ.get("GO_CONFIG_PATH") or os.path.join(
        os.path.dirname(__file__), "..", "..", "config.json"
    )
    try:
        with open(os.path.abspath(cfg_path), encoding="utf-8") as f:
            import json

            return json.load(f) or {}
    except Exception:
        return {}
