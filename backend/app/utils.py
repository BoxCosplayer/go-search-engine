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
    parts = (raw or "").strip().split()
    if not parts:
        return "", "", []
    return parts[0], " ".join(parts[1:]), parts[1:]


def render_url_template(url_tmpl: str, full_q: str, args: str, words: list[str]) -> str:
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
    if not raw:
        return ""
    q = raw.strip()
    if (len(q) >= 2) and ((q[0], q[-1]) in {('"', '"'), ("'", "'"), ("`", "`")}):
        q = q[1:-1].strip()
    return _TRAILING_PUNCT_RE.sub("", q)


def to_slug(s: str) -> str:
    if slugify is not None:
        return slugify(s or "", lowercase=True, separator="-")
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    return re.sub(r"[^a-z0-9\-_]", "", s)


def file_url_to_path(url: str) -> str:
    u = urlparse(url)
    if u.scheme != "file":
        raise ValueError("not a file URL")
    path = url2pathname(u.path or "")
    if u.netloc and u.netloc.lower() not in ("", "localhost"):
        # Build UNC path: \\server\share\path using f-string
        path = f"\\\\{u.netloc}{path.replace('/', '\\')}"
    return os.path.normpath(path)


def is_allowed_path(path: str) -> bool:
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
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def load_config():
    cfg_path = os.environ.get("GO_CONFIG_PATH") or os.path.join(
        os.path.dirname(__file__), "..", "..", "config.json"
    )
    try:
        with open(os.path.abspath(cfg_path), encoding="utf-8") as f:
            import json

            return json.load(f) or {}
    except Exception:
        return {}
