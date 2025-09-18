## TODOS

# app protocols to open apps
## go [name]

# Multi search - DONE need to add links
## go wiki ""
## go define ""
## go weather "cheltenham"
## go maps "cheltenham" -> directions

# extra go links:
## dailys [list]
## go files or folders
## milks
## cvs
## wheel
### overleaf
### pdf
## applications [list] [web]
## easter eggs
### go gamble
### go roll "x" / go flip

# dns
# export / import (db)
# dockeur on ds
# browser extension
# load html from other files very simply

from __future__ import annotations

import sqlite3
from urllib.parse import quote_plus, quote
from flask import Flask, request, redirect, abort, g, render_template_string

import sys, os, json, threading, webbrowser, subprocess, re
from urllib.parse import urlparse
from urllib.request import url2pathname

from slugify import slugify

try:
    import pystray
    from pystray import MenuItem as item, Menu
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    pystray = None  # we'll run without a tray if deps are missing

_ARG_INDEX_RE = re.compile(r"\{(\d+)\}")  # for {1}, {2}, ...

def _split_query(raw: str):
    """Return (keyword, args, all_words)."""
    parts = (raw or "").strip().split()
    if not parts:
        return "", "", []
    return parts[0], " ".join(parts[1:]), parts[1:]

def _render_template(url_tmpl: str, full_q: str, args: str, words: list[str]) -> str:
    """
    Supported placeholders:
      {q}         → full query (URL-encoded, e.g., 'wiki alan turing')
      {args}      → remainder after the keyword (URL-encoded, e.g., 'alan turing')
      {args_raw}  → remainder (unencoded)
      {args_url}  → remainder (strict-encoded with quote)
      {1},{2},..  → individual word args (URL-encoded), e.g. {1}='alan', {2}='turing'
    """
    out = (url_tmpl
           .replace("{q}", quote_plus(full_q))
           .replace("{args}", quote_plus(args))
           .replace("{args_raw}", args)
           .replace("{args_url}", quote(args, safe="")))
    # numbered args
    def _repl(m):
        i = int(m.group(1)) - 1
        return quote_plus(words[i]) if 0 <= i < len(words) else ""
    out = _ARG_INDEX_RE.sub(_repl, out)
    return out


def _make_tray_image():
    # 64x64 simple dark badge with "go"
    W = H = 64
    bg = (13, 17, 23, 255)       # #0d1117
    panel = (22, 27, 34, 255)    # #161b22
    accent = (88, 166, 255, 255) # #58a6ff
    img = Image.new("RGBA", (W, H), bg)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, W-6, H-6], 12, fill=panel)
    d.ellipse([10, 22, 26, 38], fill=accent)  # simple dot
    # Write "go" (fallback without font)
    text = "go"
    try:
        # Optional: if you ship a TTF, load it here
        font = ImageFont.load_default()
    except Exception:
        font = None
    d.text((30, 22), text, fill=accent, font=font)
    return img


def _base_dir():    # if running as a PyInstaller EXE, use the folder containing the executable
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(__file__)

BASE_DIR = _base_dir()

def _resource_path(name: str) -> str:
    # 1) external next to exe/script, 2) bundled in one-file exe, 3) fallback
    p1 = os.path.join(BASE_DIR, name)
    if os.path.exists(p1):
        return p1
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        p2 = os.path.join(sys._MEIPASS, name)  # type: ignore[attr-defined]
        if os.path.exists(p2):
            return p2
    return p1

def _file_url_to_path(url: str) -> str:
    """Convert file:// URL to a local OS path (handles Windows drive letters & UNC)."""
    u = urlparse(url)
    if u.scheme != "file":
        raise ValueError("not a file URL")
    path = url2pathname(u.path or "")
    # UNC host?
    if u.netloc and u.netloc.lower() not in ("", "localhost"):
        # \\server\share\path
        path = r"\\%s%s" % (u.netloc, path.replace("/", "\\"))
    return os.path.normpath(path)

def _is_allowed_path(path: str) -> bool:
    """Optional allowlist via GO_FILE_ALLOW (semicolon-separated absolute dirs)."""
    allow_env = os.environ.get("GO_FILE_ALLOW", "").strip()
    if not allow_env:
        # default: only allow when binding to localhost; otherwise require GO_FILE_ALLOW
        return True
    roots = [p for p in (x.strip() for x in allow_env.split(";")) if p]
    try:
        path = os.path.abspath(path)
        for root in roots:
            root = os.path.abspath(root)
            # ensure commonpath is the root
            if os.path.commonpath([path, root]) == root:
                return True
    except Exception:
        pass
    return False

def _open_file(path: str) -> None:
    """Open a file/folder with the OS default handler."""
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def load_config():
    # Optional JSON file with defaults
    cfg_path = os.environ.get("GO_CONFIG_PATH") or _resource_path("config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}
    
def _to_slug(s: str) -> str:
    try:
        return slugify(s, lowercase=True, separator='-')
    except Exception:
        # tiny fallback: lowercase, keep alnum & -_
        import re
        s = (s or "").strip().lower()
        s = re.sub(r'\s+', '-', s)
        return re.sub(r'[^a-z0-9\-_]', '', s)
    
# characters to strip at end of query
_TRAILING_PUNCT_RE = re.compile(r"""[\s'\"`#@)\]\},.!?:;]+$""")

def _sanitize_query(raw: str) -> str:
    """Trim whitespace and trailing punctuation some apps add."""
    if not raw:
        return ""
    q = raw.strip()
    # strip symmetrical quotes if the whole thing is wrapped, e.g. "gh", 'gh'
    if (len(q) >= 2) and ((q[0], q[-1]) in {('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’"), ("`", "`")}):
        q = q[1:-1].strip()
    # strip trailing punctuation (one or more)
    q = _TRAILING_PUNCT_RE.sub("", q)
    return q

DB_PATH = os.environ.get("GO_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "links.db"))
FALLBACK_URL_TEMPLATE = os.environ.get("GO_FALLBACK_URL_TEMPLATE", "")  # e.g. "https://duckduckgo.com/?q={q}"

HTML_NOT_FOUND = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Not Found – go</title>
  <style>
    :root{
      --bg:#0d1117;        /* GitHub dark background */
      --panel:#161b22;     /* panel surface */
      --text:#c9d1d9;      /* primary text */
      --muted:#8b949e;     /* secondary text */
      --border:#30363d;    /* subtle borders */
      --accent:#58a6ff;    /* links / primary */
    }
    *{box-sizing:border-box}
    html,body{height:100%}
    body{
      margin:0;
      background:var(--bg);
      color:var(--text);
      font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,'Helvetica Neue',Arial,'Noto Sans','Apple Color Emoji','Segoe UI Emoji','Segoe UI Symbol';
      line-height:1.5;
      display:grid;
      place-items:start center;   /* center horizontally; comfy top spacing */
      padding:2rem 1rem;
      text-align:center;          /* center text globally */
    }
    a{color:var(--accent);text-decoration:none}
    a:hover{text-decoration:underline}

    .wrap{
      width:min(820px,100%);
    }

    h1{margin:0 0 1rem}
    .keyword{font-weight:700;color:var(--accent)}
    .hint{color:var(--muted)}

    code,kbd{
      background:var(--panel);
      padding:0.15rem 0.35rem;border-radius:6px;
      border:1px solid var(--border);
      color:var(--text)
    }

    /* Suggestions card */
    .card{
      background:var(--panel);
      border:1px solid var(--border);
      border-radius:12px;
      padding:1rem;
      box-shadow:0 2px 12px rgba(0,0,0,.25);
      margin:0.75rem auto 0;
    }

    ul{
      list-style:none;
      padding:0;
      margin:0.25rem 0 0;
    }
    li{
      margin:0.35rem 0;
      padding:0.6rem 0.75rem;
      border:1px solid var(--border);
      border-radius:10px;
      background:rgba(255,255,255,.02);
    }
    li small{display:block;margin-top:0.25rem;color:var(--muted)}
    hr{
      border:0;
      height:1px;
      background:var(--border);
      margin:1.25rem auto;
      width:min(720px,100%);
    }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>No exact match for <span class="keyword">{{q}}</span></h1>

    {% if suggestions %}
      <div class="card">
        <p>Did you mean:</p>
        <ul>
          {% for s in suggestions %}
            <li>
              <a href="{{s['url']}}">{{s['keyword']}}</a>
              {% if s['title'] %} – {{s['title']}}{% endif %}
              <small>{{s['url']}}</small>
            </li>
          {% endfor %}
        </ul>
      </div>
    {% else %}
      <div class="card">
        <p>No suggestions in the database.</p>
      </div>
    {% endif %}

    {% if fallback_url %}
      <p class="hint">Nothing matched locally. Redirecting you to a web search would have been:<br>
      <a href="{{fallback_url}}">{{fallback_url}}</a></p>
    {% endif %}

    <hr>
    <p class="nav">
      <a href="/">← Back to Home</a>
      {% if home_prefill %} <a href="{{home_prefill}}">Home (pre-filled with “{{q}}”)</a> {% endif %}
    </p>
    <p class="hint">Tip: add a new shortcut via <code>POST /api/links</code> or the <a href="/admin">Admin UI</a>.</p>
  </div>
</body>
</html>
"""

INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>go – local shortcuts</title>
  <style>
    :root{ --bg:#0d1117; --panel:#161b22; --text:#c9d1d9; --muted:#8b949e; --border:#30363d; --accent:#58a6ff; }
    *{box-sizing:border-box}
    html,body{height:100%}
    body{
      margin:0; background:var(--bg); color:var(--text);
      font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,'Helvetica Neue',Arial,'Noto Sans','Apple Color Emoji','Segoe UI Emoji','Segoe UI Symbol';
      line-height:1.5; display:grid; place-items:center; text-align:center; padding:2rem 1rem;
    }
    a{color:var(--accent); text-decoration:none}
    a:hover{text-decoration:underline}
    .wrap{ width:min(900px,100%) }
    h1{ margin:0 0 .75rem } h2{ margin:1.5rem 0 .75rem; color:var(--muted); font-weight:600 }
    p{ margin:.25rem 0 1rem }
    code,kbd{
      background:var(--panel); padding:.15rem .35rem; border-radius:6px;
      border:1px solid var(--border); color:var(--text)
    }
    form{
      display:inline-block; background:var(--panel); border:1px solid var(--border);
      border-radius:12px; padding:.75rem; box-shadow:0 2px 12px rgba(0,0,0,.25);
    }
    input,button{ font-size:1rem; padding:.6rem .8rem; border-radius:8px; border:1px solid var(--border) }
    input[type="text"]{ width:min(26rem, 90vw); background:#0b1320; color:var(--text); outline:none; margin-right:.5rem }
    input[type="text"]:focus{ border-color:var(--accent); box-shadow:0 0 0 3px rgba(88,166,255,.25) }
    button{ background:var(--accent); color:#0b0f14; border-color:transparent; cursor:pointer; font-weight:600 }
    button:hover{ filter:brightness(1.08) }
    .meta{ margin-top:.5rem; color:var(--muted); font-size:.95rem }

    table{
      width:100%; border-collapse:collapse; margin:.75rem auto 0;
      background:var(--panel); border:1px solid var(--border);
      border-radius:12px; overflow:hidden;
    }
    th,td{ padding:.75rem .5rem; border-bottom:1px solid var(--border); text-align:center }
    thead th{ color:var(--muted); font-weight:600; background:rgba(255,255,255,.02) }
    tbody tr:nth-child(even) td{ background:rgba(255,255,255,.02) }

    .chip{
      display:inline-block; padding:.15rem .45rem; margin:.1rem;
      border:1px solid var(--border); border-radius:999px;
      background:rgba(255,255,255,.04); color:var(--text); font-size:.9rem;
    }
    .muted{ color:var(--muted) }
    .footer{ margin-top:.75rem; color:var(--muted) }
    .hidden{ display:none !important }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>go</h1>
    <p>Type <kbd>go&nbsp;&lt;keyword&gt;</kbd> in your browser's address bar (via a bookmark keyword or custom search engine) to jump to a URL.</p>

    <form action="/go" method="get" role="search" autocomplete="off">
      <input type="text" name="q" id="q" placeholder="keyword (e.g., gh)" autofocus>
      <button type="submit">Go</button>
    </form>

    <div class="meta" id="matchCount"></div>

    <h2>Links</h2>
    <table>
      <thead>
        <tr><th>Keyword</th><th>Title</th><th>URL</th><th>Lists</th></tr>
      </thead>
      <tbody id="linksBody">
        {% for row in rows %}
          <tr
            data-keyword="{{ row['keyword'] }}"
            data-title="{{ (row['title'] or '') }}"
            data-url="{{ row['url'] }}"
            data-lists="{{ (row['lists_csv'] or '') }}"
          >
            <td class="kw"><code>{{row['keyword']}}</code></td>
            <td class="ti">{{row['title'] or ''}}</td>
            <td class="ur"><a href="{{row['url']}}">{{row['url']}}</a></td>
            <td class="li">
              {% if row['lists_csv'] %}
                {% for s in row['lists_csv'].split(',') %}
                  {% set slug = s.strip() %}
                  <a class="chip" href="/lists/{{ slug }}">{{ slug }}</a>
                {% endfor %}
              {% else %}
                <span class="muted">—</span>
              {% endif %}
            </td>
          </tr>
        {% endfor %}
        <tr id="noRows" class="hidden">
          <td colspan="4" class="muted">No matches.</td>
        </tr>
      </tbody>
    </table>

    <p class="footer"><a href="/lists">Lists</a> · <a href="/admin">Admin UI</a> · <a href="/healthz">health</a></p>
  </div>

  <script>
    (function(){
      const input = document.getElementById('q');
      const tbody = document.getElementById('linksBody');
      const rows  = Array.from(tbody.querySelectorAll('tr')).filter(tr => tr.id !== 'noRows');
      const noRows = document.getElementById('noRows');
      const counter = document.getElementById('matchCount');

      function norm(s){ return (s || '').toString().toLowerCase(); }

      function applyFilter() {
        const q = norm(input.value.trim());
        let shown = 0;
        for (const tr of rows) {
          const hay = (
            (tr.dataset.keyword || '') + ' ' +
            (tr.dataset.title || '')   + ' ' +
            (tr.dataset.url || '')     + ' ' +
            (tr.dataset.lists || '')
          ).toLowerCase();
          const show = !q || hay.includes(q);
          tr.classList.toggle('hidden', !show);
          if (show) shown++;
        }
        noRows.classList.toggle('hidden', shown !== 0);
        counter.textContent = (q ? `Showing ${shown} of ${rows.length} matches` : `${rows.length} total`);
      }

      // Prefill from ?q= if present
      const params = new URLSearchParams(location.search);
      if (params.has('q')) input.value = params.get('q');

      // Debounced filter
      let t; const DEBOUNCE_MS = 60;
      input.addEventListener('input', () => { clearTimeout(t); t = setTimeout(applyFilter, DEBOUNCE_MS); });

      input.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && input.value) { input.value = ''; applyFilter(); e.preventDefault(); }
      });

      applyFilter();
    })();
  </script>
</body>
</html>
"""

ADMIN_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>go – Admin</title>
  <style>
    :root{
      --bg:#0d1117; --panel:#161b22; --text:#c9d1d9; --muted:#8b949e;
      --border:#30363d; --accent:#58a6ff; --danger:#f85149;
    }
    *{box-sizing:border-box}
    html,body{height:100%}
    body{
      margin:0; background:var(--bg); color:var(--text);
      font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,'Helvetica Neue',Arial,'Noto Sans','Apple Color Emoji','Segoe UI Emoji','Segoe UI Symbol';
      line-height:1.5; display:grid; place-items:start center; padding:2rem 1rem;
      text-align:center;
    }
    a{color:var(--accent); text-decoration:none}
    a:hover{text-decoration:underline}

    .wrap{ width:min(980px,100%) }
    h1{margin:0 0 1rem}
    h2{margin:1.5rem 0 .75rem; color:var(--muted); font-weight:600}
    .muted{color:var(--muted)}

    code,kbd{
      background:var(--panel); padding:.15rem .35rem; border-radius:6px;
      border:1px solid var(--border); color:var(--text)
    }

    .row{display:grid; grid-template-columns:1fr 1fr; gap:1rem; align-items:start}
    @media (max-width: 900px){ .row{grid-template-columns:1fr} }

    /* Cards */
    form.add-form, form.list-form{
      background:var(--panel); border:1px solid var(--border); border-radius:12px;
      padding:1rem; box-shadow:0 2px 12px rgba(0,0,0,.25);
      text-align:center;
    }
    form.add-form{
      background:var(--panel);
      border:1px solid var(--border);
      border-radius:12px;
      padding:1rem;
      box-shadow:0 2px 12px rgba(0,0,0,.25);
      text-align:center;

      /* NEW: make it long and full-width of the grid */
      width:100%;
      max-width:clamp(900px, 95vw, 1200px);
      margin:0 auto;
      grid-column:1 / -1; /* span both columns */
    }

    /* Keep Create list as a normal card */
    form.list-form{
      background:var(--panel);
      border:1px solid var(--border);
      border-radius:12px;
      padding:1rem;
      box-shadow:0 2px 12px rgba(0,0,0,.25);
      text-align:center;
      max-width:560px;
      margin:0 auto;
    }

    .wrap{ width:min(1200px, 100%) }
    /* Alternative: keep two columns, make left column wider */
    .row{ display:grid; grid-template-columns:2.2fr 1fr; gap:1rem; align-items:start }
    form.add-form{ grid-column:auto; max-width:100% }

    label{display:block; margin-top:.75rem}
    input,button{
      font-size:1rem; padding:.6rem .8rem; border-radius:8px; border:1px solid var(--border)
    }
    input{
      width:100%; max-width:100%;
      background:#0b1320; color:var(--text); outline:none;
      text-align:center;
    }
    input:focus{border-color:var(--accent); box-shadow:0 0 0 3px rgba(88,166,255,.25)}

    button{
      margin-top:.9rem; background:var(--accent); color:#0b0f14;
      border-color:transparent; cursor:pointer; font-weight:600
    }
    button:hover{filter:brightness(1.08)}
    .danger{background:var(--danger); color:#fff}

    /* Filter bar */
    .filter-card{
      display:inline-block; background:var(--panel); border:1px solid var(--border);
      border-radius:12px; padding:.6rem .8rem; margin-top:.5rem;
      box-shadow:0 2px 12px rgba(0,0,0,.25)
    }
    .filter-input{
      width:min(26rem,90vw); background:#0b1320; color:var(--text);
      outline:none; border:1px solid var(--border); border-radius:8px;
      padding:.55rem .75rem; text-align:center
    }
    .meta{margin-top:.4rem; color:var(--muted); font-size:.95rem}

    /* Table */
    table{
      width:100%; border-collapse:collapse; margin:1rem auto 0;
      background:var(--panel); border:1px solid var(--border);
      border-radius:12px; overflow:hidden; text-align:center
    }
    th,td{
      padding:.75rem .5rem; border-bottom:1px solid var(--border);
      text-align:center; vertical-align:middle; /* center vertically to keep rows compact */
    }
    thead th{color:var(--muted); font-weight:600; background:rgba(255,255,255,.02)}
    tbody tr:nth-child(even) td{background:rgba(255,255,255,.02)}

    .actions form{display:inline-block; background:transparent; border:none; padding:0; box-shadow:none}

    /* --- FIX: keep Update inline next to input, avoid row growth --- */
    .lists-edit{display:flex; justify-content:center}
    .lists-edit form{
      display:flex; align-items:center; gap:.5rem; margin:0; flex-wrap:nowrap;
    }
    .lists-input{
      width:auto;           /* override global input width */
      min-width:12rem;
      text-align:center;
    }
    .lists-edit button{
      margin-top:0;         /* no vertical offset inside table row */
    }
    /* -------------------------------------------------------------- */

    .footer{margin-top:1rem}
    .hidden{display:none!important}
    .chip{
      display:inline-block; padding:.15rem .45rem; border:1px solid var(--border);
      border-radius:999px; background:rgba(255,255,255,.04); margin:.1rem
    }

    /* Center the Delete button vertically in its cell */
    td.actions { 
      display: flex; 
      align-items: center; 
      justify-content: center; 
    }

    td.actions form { 
      margin: 0; 
    }

    td.actions button { 
      margin-top: 0;       /* override global button margin */
    }

    /* Page/container limits */
    .wrap{ width:min(1400px, 100%) }                /* let page be wider than before */

    /* Table wrapper that can grow but has a max width */
    .table-wrap{
      width: clamp(900px, 95vw, 1280px);            /* grows with content up to 1280px */
      margin: 0 auto;
      overflow-x: auto;                             /* horizontal scroll past the cap */
      border-radius: 12px;
    }

    /* Table */
    table{ width:100%; table-layout:auto }          /* auto columns, fill wrapper */

    /* Dynamic column sizing */
    .col-key, .col-actions{ width:1% }              /* shrink-to-fit */
    .col-lists{ width:0.1% }

    th:nth-child(1), td:nth-child(1),
    th:nth-child(5), td:nth-child(5){ white-space:nowrap }

    /* Keep URLs on one line */
    td:nth-child(3) a{ white-space:normal; overflow-wrap:anywhere; }

    /* Lists editor stays compact & inline */
    .lists-input{ width: clamp(10rem, 22vw, 18rem); }
    .lists-edit form{ display:flex; align-items:center; gap:.5rem; margin:0; flex-wrap:nowrap; }
    .lists-edit button, .actions button{ margin-top:0; }
    td.actions{ display:flex; align-items:center; justify-content:center; }

  </style>
</head>
<body>
  <div class="wrap">
    <h1>Admin</h1>

    <div class="row">
      <!-- Add link -->
      <form action="/admin/add" method="post" class="add-form">
        <h2>Add link</h2>
        <label>Keyword
          <input name="keyword" required placeholder="gh">
        </label>
        <label>Title
          <input name="title" placeholder="GitHub">
        </label>
        <label>URL
          <input name="url" required placeholder="https://github.com">
        </label>
        <button type="submit">Save</button>
      </form>

      <!-- Create list -->
      <form action="/admin/list-add" method="post" class="list-form">
        <h2>Create list</h2>
        <label>Name
          <input name="name" placeholder="Work Projects">
        </label>
        <label>Description (optional)
          <input name="description" placeholder="Links used for work">
        </label>
        <button type="submit">Add list</button>
        <p class="meta">Browse: <a href="/lists">All lists</a></p>
      </form>
    </div>

    <h2>Existing</h2>

    <!-- Live filter bar -->
    <div class="filter-card" role="search">
      <input id="filter" class="filter-input" type="text" placeholder="Filter links (keyword, title, or URL)">
      <div id="matchCount" class="meta"></div>
    </div>

    <table>
      <colgroup>
        <col class="col-key">
        <col class="col-title">
        <col class="col-url">
        <col class="col-lists">
        <col class="col-actions">
      </colgroup>

      <thead>
        <tr><th>Keyword</th><th>Title</th><th>URL</th><th>Lists</th><th></th></tr>
      </thead>
      <tbody id="linksBody">
        {% for row in rows %}
          <tr
            data-keyword="{{row['keyword']}}"
            data-title="{{row['title'] or ''}}"
            data-url="{{row['url']}}"
          >
            <td><code>{{row['keyword']}}</code></td>
            <td>{{row['title'] or ''}}</td>
            <td><a href="{{row['url']}}">{{row['url']}}</a></td>
            <td>
              <div class="lists-edit">
                <form action="/admin/set-lists" method="post">
                  <input type="hidden" name="keyword" value="{{row['keyword']}}">
                  <input class="lists-input" name="slugs" list="lists_suggestions" placeholder="comma,separated" value="{{row['lists_csv']}}">
                  <button type="submit">Update</button>
                </form>
              </div>
              {% if row['lists_csv'] %}
                <div class="meta">
                  {% for s in row['lists_csv'].split(',') %}
                    <span class="chip">{{ s.strip() }}</span>
                  {% endfor %}
                </div>
              {% endif %}
            </td>
            <td class="actions">
              <form action="/admin/delete" method="post">
                <input type="hidden" name="keyword" value="{{row['keyword']}}">
                <button class="danger" type="submit" onclick="return confirm('Delete {{row['keyword']}}?')">Delete</button>
              </form>
            </td>
          </tr>
        {% endfor %}
        <tr id="noRows" class="hidden">
          <td colspan="5" class="muted">No matches.</td>
        </tr>
      </tbody>
    </table>

    <p class="footer"><a href="/">Home</a> · <a href="/lists">Browse Lists</a></p>
  </div>

  <!-- list suggestions -->
  <datalist id="lists_suggestions">
    {% for li in all_lists %}
      <option value="{{ li['slug'] }}">{{ li['name'] }}</option>
    {% endfor %}
  </datalist>

  <script>
    (function(){
      const input = document.getElementById('filter');
      const tbody = document.getElementById('linksBody');
      if (!input || !tbody) return;

      const rows = Array.from(tbody.querySelectorAll('tr')).filter(tr => tr.id !== 'noRows');
      const noRows = document.getElementById('noRows');
      const counter = document.getElementById('matchCount');

      const norm = s => (s || '').toString().toLowerCase();

      function applyFilter(){
        const q = norm(input.value.trim());
        let shown = 0;
        for (const tr of rows){
          const hay = (tr.dataset.keyword + ' ' + (tr.dataset.title || '') + ' ' + tr.dataset.url).toLowerCase();
          const show = !q || hay.includes(q);
          tr.classList.toggle('hidden', !show);
          if (show) shown++;
        }
        if (noRows) noRows.classList.toggle('hidden', shown !== 0);
        if (counter) counter.textContent = q ? `Showing ${shown} of ${rows.length}` : `${rows.length} total`;
      }

      let t; const DEBOUNCE_MS = 60;
      input.addEventListener('input', () => { clearTimeout(t); t = setTimeout(applyFilter, DEBOUNCE_MS); });

      const params = new URLSearchParams(location.search);
      if (params.has('q')) input.value = params.get('q');

      applyFilter();
    })();
  </script>
</body>
</html>
"""

FILE_OPEN_HTML = """
<!doctype html><meta charset="utf-8">
<title>Opened</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,Arial; margin:2rem;
       background:#0d1117;color:#c9d1d9}
  a{color:#58a6ff;text-decoration:none}
  a:hover{text-decoration:underline}
  code{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:.15rem .35rem}
</style>
<h1>Opened</h1>
<p>Asked the OS to open:</p>
<p><code>{{path}}</code></p>
<p><a href="/">Back</a> · <a href="/admin">Admin</a></p>
"""

LISTS_INDEX_HTML = """
<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>go – Lists</title>
<style>
:root{--bg:#0d1117;--panel:#161b22;--text:#c9d1d9;--muted:#8b949e;--border:#30363d;--accent:#58a6ff;--danger:#f85149}
*{box-sizing:border-box} html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,Arial;
     line-height:1.5;display:grid;place-items:start center;padding:2rem 1rem;text-align:center}
a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}
.wrap{width:min(900px,100%)}
h1{margin:0 0 .75rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:.75rem;margin-top:1rem}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:.9rem;display:flex;flex-direction:column;gap:.4rem}
.name{font-weight:600}
.count{color:var(--muted);font-size:.95rem}
.meta{margin-top:.25rem;color:var(--muted)}
.actions{display:flex;gap:.5rem;justify-content:center;margin-top:.4rem}
.btn{font-size:0.95rem;padding:.45rem .8rem;border-radius:8px;border:1px solid var(--border);cursor:pointer}
.btn-danger{background:var(--danger);color:#fff;border-color:transparent}
</style></head><body>
<div class="wrap">
  <h1>Lists</h1>
  <div class="grid">
    {% for li in lists %}
      <div class="card">
        <a class="name" href="/lists/{{li['slug']}}">{{li['name']}}</a>
        <div class="count">{{li['count']}} link{{ '' if li['count']==1 else 's' }}</div>
        {% if li['description'] %}<div class="meta">{{li['description']}}</div>{% endif %}
        <div class="actions">
          <form action="/admin/list-delete" method="post" onsubmit="return confirm('Delete list {{ li['name'] }}? This only removes the list and its associations, not your links.');">
            <input type="hidden" name="slug" value="{{ li['slug'] }}">
            <button class="btn btn-danger" type="submit">Delete</button>
          </form>
        </div>
      </div>
    {% endfor %}
    {% if not lists %}<p class="meta" style="grid-column:1/-1">No lists yet. Create one in Admin.</p>{% endif %}
  </div>
  <p class="meta" style="margin-top:1rem"><a href="/">Home</a> · <a href="/admin">Admin</a></p>
</div>
</body></html>
"""

LIST_PAGE_HTML = """
<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>go – {{list['name']}}</title>
<style>
:root{--bg:#0d1117;--panel:#161b22;--text:#c9d1d9;--muted:#8b949e;--border:#30363d;--accent:#58a6ff;--danger:#f85149}
*{box-sizing:border-box} html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,Arial;
     line-height:1.5;display:grid;place-items:center;padding:2rem 1rem;text-align:center}
a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}
.wrap{width:min(900px,100%)}
h1{margin:0 0 .25rem} .meta{color:var(--muted)}
.header-actions{margin:.5rem 0;display:flex;gap:.5rem;justify-content:center}
.btn{font-size:.95rem;padding:.45rem .8rem;border-radius:8px;border:1px solid var(--border);cursor:pointer;background:var(--panel);color:var(--text)}
.btn-danger{background:var(--danger);border-color:transparent;color:#fff}
.filter{display:inline-block;background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:.6rem .8rem;margin:.75rem 0}
.filter input{width:min(26rem,90vw);background:#0b1320;color:var(--text);border:1px solid var(--border);border-radius:8px;padding:.55rem .75rem}
table{width:100%;border-collapse:collapse;margin:.5rem auto 0;background:var(--panel);border:1px solid var(--border);border-radius:12px;overflow:hidden}
th,td{padding:.75rem .5rem;border-bottom:1px solid var(--border);text-align:center}
thead th{color:var(--muted);font-weight:600;background:rgba(255,255,255,.02)}
tbody tr:nth-child(even) td{background:rgba(255,255,255,.02)}
.hidden{display:none!important}
</style></head><body>
<div class="wrap">
  <h1>{{list['name']}}</h1>
  {% if list['description'] %}<div class="meta">{{list['description']}}</div>{% endif %}

  <div class="header-actions">
    <a class="btn" href="/lists">All lists</a>
    <form action="/admin/list-delete" method="post" onsubmit="return confirm('Delete list {{ list['name'] }}? This only removes the list and its associations, not your links.');">
      <input type="hidden" name="slug" value="{{ list['slug'] }}">
      <button class="btn btn-danger" type="submit">Delete list</button>
    </form>
  </div>

  <div class="filter"><input id="q" type="text" placeholder="Filter links…"></div>
  <div class="meta" id="count"></div>

  <table>
    <thead><tr><th>Keyword</th><th>Title</th><th>URL</th></tr></thead>
    <tbody id="body">
      {% for r in rows %}
        <tr data-hay="{{ (r['keyword'] ~ ' ' ~ (r['title'] or '') ~ ' ' ~ r['url']).lower() }}">
          <td><code>{{r['keyword']}}</code></td>
          <td>{{r['title'] or ''}}</td>
          <td><a href="{{r['url']}}">{{r['url']}}</a></td>
        </tr>
      {% endfor %}
      <tr id="noRows" class="hidden"><td colspan="3" class="meta">No matches.</td></tr>
    </tbody>
  </table>

  <p class="meta" style="margin-top:.75rem"><a href="/">Home</a> · <a href="/admin">Admin</a></p>
</div>
<script>
(function(){
  const q=document.getElementById('q'), tbody=document.getElementById('body'), rows=[...tbody.querySelectorAll('tr')].filter(tr=>tr.id!=='noRows'), no=document.getElementById('noRows'), cnt=document.getElementById('count');
  function f(){ const v=(q.value||'').toLowerCase().trim(); let n=0; for(const tr of rows){const ok=!v||tr.dataset.hay.includes(v); tr.classList.toggle('hidden',!ok); if(ok)n++;} no.classList.toggle('hidden',n!==0); cnt.textContent = v?`Showing ${n} of ${rows.length}`:`${rows.length} total`; }
  let t; q.addEventListener('input',()=>{clearTimeout(t);t=setTimeout(f,60)}); f();
})();
</script>
</body></html>
"""



app = Flask(__name__)

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    db.execute("""
    CREATE TABLE IF NOT EXISTS links (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      keyword TEXT NOT NULL UNIQUE,
      url TEXT NOT NULL,
      title TEXT
    );
    """)
    db.commit()

def ensure_lists_schema(db):
  db.execute("""
  CREATE TABLE IF NOT EXISTS lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT
  );
  """)
  db.execute("""
  CREATE TABLE IF NOT EXISTS link_lists (
    link_id INTEGER NOT NULL,
    list_id INTEGER NOT NULL,
    PRIMARY KEY (link_id, list_id),
    FOREIGN KEY (link_id) REFERENCES links(id) ON DELETE CASCADE,
    FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE CASCADE
  );
  """)
  db.commit()


@app.route("/healthz")
def healthz():
    # Basic health endpoint
    try:
        db = get_db()
        db.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}, 500

@app.route("/")
def index():
    db = get_db()
    # If you have the lists schema, this will include list slugs per link.
    rows = db.execute("""
        SELECT l.keyword, l.title, l.url,
               IFNULL(GROUP_CONCAT(li.slug, ', '), '') AS lists_csv
        FROM links l
        LEFT JOIN link_lists ll ON ll.link_id = l.id
        LEFT JOIN lists li ON li.id = ll.list_id
        GROUP BY l.id
        ORDER BY l.keyword COLLATE NOCASE
    """).fetchall()
    return render_template_string(INDEX_HTML, rows=rows)


@app.route("/go")
def go():
    """
    Main redirector endpoint. Accepts ?q=<keyword> and sends a 302 to the stored URL.
    - Exact match on keyword (case-insensitive)
    - If no exact match, shows a suggestions page and (optionally) a fallback search URL
    """
    raw = (request.args.get("q") or "").strip()
    q = _sanitize_query(raw)
    if not q:
        abort(400, "Missing q")

    db = get_db()
    key, rest, words = _split_query(q)
    exact = db.execute("SELECT url FROM links WHERE lower(keyword) = lower(?)", (q,)).fetchone()

    prov = None
    if not exact:
        prov = db.execute("SELECT url FROM links WHERE lower(keyword) = lower(?)", (key,)).fetchone()

    if exact and not prov:
        url = exact["url"]

        if url.startswith(("http://", "https://")):
            return redirect(url, code=302)

        if url.startswith("file://"):
            try:
                path = _file_url_to_path(url)
            except Exception as e:
                return (f"Bad file URL: {e}", 400)

            # Safety: only allow local opens (keep server bound to 127.0.0.1) and/or allowlist
            if request.host.split(":")[0] not in ("127.0.0.1", "localhost") and not os.environ.get("GO_FILE_ALLOW"):
                return ("Refusing to open local files over non-localhost. Bind to 127.0.0.1 or set GO_FILE_ALLOW.", 403)

            if not _is_allowed_path(path):
                return ("Path not allowed. Set GO_FILE_ALLOW to include this directory.", 403)

            if not (os.path.exists(path)):
                return (f"File/folder not found: {path}", 404)

            try:
                _open_file(path)
            except Exception as e:
                return (f"Failed to open: {e}", 500)

            # Show a tiny confirmation page (no redirect to file://)
            return render_template_string(FILE_OPEN_HTML, path=path), 200

        return redirect(url, code=302)
    
    if prov:
      url_tmpl = prov["url"]
      # If it's a template (contains placeholders), render it
      if any(tok in url_tmpl for tok in ("{args", "{q}", "{1}", "{2}", "{3}")):
          final_url = _render_template(url_tmpl, q, rest, words)
          if final_url.startswith(("http://", "https://")):
              return redirect(final_url, code=302)
          return ("Template resolved to unsupported scheme", 400)
      # Not a template: if no args, just go; if args present, ignore args and go
      if url_tmpl.startswith(("http://", "https://")):
          return redirect(url_tmpl, code=302)
      if url_tmpl.startswith("file://"):
          path = _file_url_to_path(url_tmpl)
          # ... (unchanged)
          return render_template_string(FILE_OPEN_HTML, path=path), 200
      return ("Unsupported URL scheme", 400)
    

    # Collect suggestions (prefix/substring matches on keyword/title/url)
    like = f"%{q}%"
    suggestions = db.execute(
        """
        SELECT keyword, title, url
        FROM links
        WHERE keyword LIKE ? OR (title IS NOT NULL AND title LIKE ?) OR url LIKE ?
        ORDER BY keyword COLLATE NOCASE LIMIT 10
        """,
        (like, like, like)
    ).fetchall()

    fallback_url = ""
    if FALLBACK_URL_TEMPLATE:
        fallback_url = FALLBACK_URL_TEMPLATE.format(q=quote_plus(q))

    return render_template_string(
        HTML_NOT_FOUND,
        q=q,
        suggestions=[dict(x) for x in suggestions],
        fallback_url=fallback_url
    ), 404


# ---- Minimal admin UI (no auth, intended for localhost only) ----
@app.route("/admin")
def admin():
    db = get_db()
    ensure_lists_schema(db)
    rows = db.execute("""
    SELECT l.id, l.keyword, l.title, l.url,
           IFNULL(GROUP_CONCAT(li.slug, ', '), '') AS lists_csv
    FROM links l
    LEFT JOIN link_lists ll ON ll.link_id = l.id
    LEFT JOIN lists li ON li.id = ll.list_id
    GROUP BY l.id
    ORDER BY l.keyword COLLATE NOCASE
    """).fetchall()

    all_lists = db.execute("SELECT slug, name FROM lists ORDER BY name COLLATE NOCASE").fetchall()
    return render_template_string(ADMIN_HTML, rows=rows, all_lists=all_lists)

@app.route("/admin/add", methods=["POST"])
def admin_add():
    keyword = (request.form.get("keyword") or "").strip()
    title = (request.form.get("title") or "").strip() or None
    url = (request.form.get("url") or "").strip()

    if not keyword or not url:
        abort(400, "Keyword and URL required")
    # if not (url.startswith("http://") or url.startswith("https://")):
    #     abort(400, "URL must start with http:// or https://")

    db = get_db()
    init_db()
    ensure_lists_schema(get_db())
    try:
        db.execute("INSERT INTO links(keyword, url, title) VALUES (?, ?, ?)", (keyword, url, title))
        db.commit()
    except sqlite3.IntegrityError:
        abort(400, f"Keyword '{keyword}' already exists")
    return redirect("/admin")

@app.route("/admin/delete", methods=["POST"])
def admin_delete():
    keyword = (request.form.get("keyword") or "").strip()
    if not keyword:
        abort(400, "Keyword required")
    db = get_db()
    db.execute("DELETE FROM links WHERE lower(keyword) = lower(?)", (keyword,))
    db.commit()
    return redirect("/admin")

@app.route("/admin/list-add", methods=["POST"])
def admin_list_add():
    db = get_db()
    ensure_lists_schema(db)
    name = (request.form.get("name") or "").strip()
    slug = (request.form.get("slug") or "").strip()
    desc = (request.form.get("description") or "").strip() or None
    if not name and not slug:
        abort(400, "name or slug required")
    if not slug:
        slug = _to_slug(name)
    if not name:
        name = slug.replace("-", " ").title()
    try:
        db.execute("INSERT INTO lists(slug, name, description) VALUES (?, ?, ?)", (slug, name, desc))
        db.commit()
    except sqlite3.IntegrityError:
        abort(400, f"List '{slug}' already exists")
    
    # Create a link to the list
    base_url = request.host_url.rstrip("/")
    list_url = f"{base_url}/lists/{slug}"
    title    = f"List - {name}"

    try:
        db.execute(
            "INSERT INTO links(keyword, url, title) VALUES (?, ?, ?)",
            (slug, list_url, title)
        )
        db.commit()
    except sqlite3.IntegrityError:
        return None
    
    return redirect("/admin")

@app.route("/admin/set-lists", methods=["POST"])
def admin_set_lists():
  
    db = get_db()
    ensure_lists_schema(db)
    keyword = (request.form.get("keyword") or "").strip()
    slugs_raw = (request.form.get("slugs") or "").strip()

    link = db.execute("SELECT id FROM links WHERE lower(keyword)=lower(?)", (keyword,)).fetchone()
    if not link:
        abort(404, "link not found")
    link_id = link["id"]

    # parse CSV of slugs, create any missing lists automatically
    slugs = [s.strip().lower() for s in slugs_raw.split(",") if s.strip()]
    slugs = sorted(set(slugs))

    for slug in slugs:
        row = db.execute("SELECT id FROM lists WHERE slug=?", (slug,)).fetchone()
        if not row:
            # auto-create with pretty name
            name = slug.replace("-", " ").title()
            db.execute("INSERT INTO lists(slug, name) VALUES (?, ?)", (slug, name))
    db.commit()

    # Reset associations
    db.execute("DELETE FROM link_lists WHERE link_id=?", (link_id,))
    for slug in slugs:
        list_id = db.execute("SELECT id FROM lists WHERE slug=?", (slug,)).fetchone()["id"]
        db.execute("INSERT OR IGNORE INTO link_lists(link_id, list_id) VALUES (?, ?)", (link_id, list_id))
    db.commit()
    return redirect("/admin")

@app.route("/admin/list-delete", methods=["POST"])
def admin_list_delete():
    db = get_db()
    slug = (request.form.get("slug") or "").strip()
    if not slug:
        abort(400, "missing slug")
    row = db.execute("SELECT id FROM lists WHERE lower(slug)=lower(?)", (slug,)).fetchone()
    if not row:
        abort(404, "list not found")
    db.execute("DELETE FROM lists WHERE id=?", (row["id"],))
    db.commit()
    return redirect("/lists")


@app.route("/lists")
def lists_index():
    db = get_db()
    ensure_lists_schema(db)
    rows = db.execute("""
    SELECT li.slug, li.name, li.description, COUNT(ll.link_id) AS count
    FROM lists li
    LEFT JOIN link_lists ll ON ll.list_id = li.id
    GROUP BY li.id
    ORDER BY li.name COLLATE NOCASE
    """).fetchall()
    return render_template_string(LISTS_INDEX_HTML, lists=rows)

@app.route("/lists/<slug>")
def lists_view(slug):
    db = get_db()
    ensure_lists_schema(db)
    info = db.execute("SELECT id, slug, name, description FROM lists WHERE lower(slug)=lower(?)", (slug,)).fetchone()
    if not info:
        abort(404, "list not found")
    rows = db.execute("""
    SELECT l.keyword, l.title, l.url
    FROM links l
    JOIN link_lists ll ON ll.link_id = l.id
    WHERE ll.list_id = ?
    ORDER BY l.keyword COLLATE NOCASE
    """, (info["id"],)).fetchall()
    return render_template_string(LIST_PAGE_HTML, list=info, rows=rows)


# ---- JSON API for scriptable management ----
@app.route("/api/links", methods=["GET", "POST"])
def api_links():
    db = get_db()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        keyword = (data.get("keyword") or "").strip()
        url = (data.get("url") or "").strip()
        title = (data.get("title") or "").strip() or None
        if not keyword or not url:
            return {"error": "keyword and url are required"}, 400
        if not (url.startswith("http://") or url.startswith("https://")):
            return {"error": "url must start with http:// or https://"}, 400
        init_db()
        ensure_lists_schema(get_db())
        try:
            db.execute("INSERT INTO links(keyword, url, title) VALUES (?, ?, ?)", (keyword, url, title))
            # TODO
            db.commit()
        except sqlite3.IntegrityError:
            return {"error": f"keyword '{keyword}' already exists"}, 400
        return {"ok": True}
    else:
        rows = db.execute("SELECT keyword, title, url FROM links ORDER BY keyword COLLATE NOCASE").fetchall()
        return {"links": [dict(r) for r in rows]}
    
@app.route("/api/lists", methods=["GET","POST"])
def api_lists():
    db = get_db(); ensure_lists_schema(db)
    if request.method == "POST":
        data = request.get_json(force=True)
        slug = (data.get("slug") or "").strip()
        name = (data.get("name") or "").strip()
        desc = (data.get("description") or "").strip() or None
        if not slug and not name: return {"error":"slug or name required"}, 400
        if not slug: slug = _to_slug(name)
        if not name: name = slug.replace("-", " ").title()
        try:
            db.execute("INSERT INTO lists(slug,name,description) VALUES (?,?,?)",(slug,name,desc))
            db.commit()
        except sqlite3.IntegrityError:
            return {"error":"slug exists"}, 400
        
        # Create a link to the list
        base_url = request.host_url.rstrip("/")
        list_url = f"{base_url}/lists/{slug}"
        title    = f"List - {name}"

        try:
            db.execute(
                "INSERT INTO links(keyword, url, title) VALUES (?, ?, ?)",
                (slug, list_url, title)
            )
            db.commit()
        except sqlite3.IntegrityError:
            return None

        return {"ok":True}
    rows = db.execute("SELECT slug,name,description FROM lists ORDER BY name COLLATE NOCASE").fetchall()
    return {"lists":[dict(r) for r in rows]}

    
def _base_dir():
    # if running as a PyInstaller EXE, use the folder containing the executable
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # normal Python run: use the script directory
    return os.path.dirname(__file__)


BASE_DIR = _base_dir()

# replace your existing DB_PATH line with:
DB_PATH = os.environ.get(
    "GO_DB_PATH",
    os.path.join(BASE_DIR, "data", "links.db")
)

if __name__ == "__main__":
    # --- ensure DB exists (same as before) ---
    base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(__file__)
    os.makedirs(os.path.join(base_dir, "data"), exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          keyword TEXT NOT NULL UNIQUE,
          url TEXT NOT NULL,
          title TEXT
        );
        """)
        db.commit()

    # --- config & defaults (adjust if you added argparse earlier) ---
    host = os.environ.get("GO_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"

    # --- run Flask in a background thread ---
    def _run_server():
        # Important: disable reloader when using threads/tray
        app.run(host=host, port=port, debug=debug, use_reloader=False)

    t = threading.Thread(target=_run_server, daemon=True)
    t.start()

    # --- system tray icon (blocking on main thread) ---
    if pystray is not None:
        base_url = f"http://{host}:{port}"

        def open_home(icon, _): webbrowser.open(f"{base_url}/")
        def open_admin(icon, _): webbrowser.open(f"{base_url}/admin")
        def quit_app(icon, _):
            icon.visible = False
            os._exit(0)  # kill the process cleanly

        image = _make_tray_image()
        menu = Menu(
            item(f"Running on {host}:{port}", None, enabled=False),
            item("Open Home", open_home),
            item("Open Admin", open_admin),
            item("Quit", quit_app),
        )

        tray = pystray.Icon("go-server", image, "go-server", menu)
        tray.run()
    else:
        # Fallback: if pystray/pillow not installed, just block here
        t.join()

