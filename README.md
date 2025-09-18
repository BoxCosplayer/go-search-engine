# go – local Flask redirector

This tiny Flask app lets you type `go <keyword>` in your browser's address bar and jump straight to a stored URL.

## How it works

- You create shortcuts in a local SQLite database mapping a `keyword` → `URL` (optionally a `title`).
- Your browser sends the search term to `http://127.0.0.1:5000/go?q=%s`.
- The server looks up the keyword:
  - **Exact match**: 302 redirect to the saved URL.
  - **No exact match**: shows a small page with suggestions from substring matches. If `GO_FALLBACK_URL_TEMPLATE` is set, it shows a hint of a fallback search URL.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# (Optional) initialize and import sample shortcuts
python init_db.py links.csv

# run the server
python app.py
```

By default it listens on `127.0.0.1:5000` and stores data in `data/links.db`.

## Add to Firefox (no extension needed)

**Option A – Bookmark keyword (recommended, works everywhere):**

1. Create a new bookmark with URL: `http://127.0.0.1:5000/go?q=%s`
2. Set the bookmark's **Keyword** to `go`.
3. In the address bar, type: `go gh` → jumps to GitHub, etc.

**Option B – Custom search engine entry:**

Some Firefox builds let you add a custom engine under Settings → Search, using the same URL template `http://127.0.0.1:5000/go?q=%s` and giving it a keyword `go`. If your build doesn't expose that UI, Option A works universally.

## Managing shortcuts

- Open `http://127.0.0.1:5000/admin` for a tiny UI to add/delete entries.
- Or use the JSON API:

```bash
curl -X POST http://127.0.0.1:5000/api/links \
  -H "content-type: application/json" \
  -d '{"keyword":"cal","title":"My Calendar","url":"https://calendar.google.com"}'
```

List all links:

```bash
curl http://127.0.0.1:5000/api/links
```

## Environment variables

- `GO_DB_PATH` – path to the SQLite DB (default: `data/links.db` next to `app.py`)
- `GO_FALLBACK_URL_TEMPLATE` – optional template for non-matches, e.g. `https://duckduckgo.com/?q={q}`
- `PORT` – port to bind (default: `5000`)
- `FLASK_DEBUG` – set to `1` for auto-reload & debug

## Notes

- The admin UI has **no auth** and is meant for `localhost` use only.
- URLs must start with `http://` or `https://` to avoid unsafe schemes.
- Matching is case-insensitive for exact keyword matches; suggestions use substring matches across keyword/title/url.
