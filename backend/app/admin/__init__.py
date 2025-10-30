import json

from flask import Blueprint, abort, redirect, render_template, request

from ..db import ensure_lists_schema, get_db, init_db
from .. import utils
from ..utils import GoConfig, _discover_config_path, load_config, to_slug

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/")
def admin_home():
    """Render the Admin home page.

    Lists all links with their associated list slugs and provides data for the
    lists datalist suggestions.

    Returns:
        A rendered HTML page (admin/index.html).
    """
    db = get_db()
    ensure_lists_schema(db)
    rows = db.execute(
        """
        SELECT l.id, l.keyword, l.title, l.url,
               IFNULL(GROUP_CONCAT(li.slug, ', '), '') AS lists_csv
        FROM links l
        LEFT JOIN link_lists ll ON ll.link_id = l.id
        LEFT JOIN lists li ON li.id = ll.list_id
        GROUP BY l.id
        ORDER BY l.keyword COLLATE NOCASE
        """
    ).fetchall()

    all_lists = db.execute("SELECT slug, name FROM lists ORDER BY name COLLATE NOCASE").fetchall()
    return render_template("admin/index.html", rows=rows, all_lists=all_lists)


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
        }

        payload = {
            "host": form_values["host"],
            "port": form_values["port"],
            "debug": form_values["debug"],
            "db_path": form_values["db_path"],
            "allow_files": form_values["allow_files"],
            "fallback_url": form_values["fallback_url"],
            "file_allow": file_allow_list,
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


@admin_bp.route("/add", methods=["POST"])
def admin_add():
    """Create a new link from form data.

    Expects form fields:
        - keyword (required)
        - url (required)
        - title (optional)

    On success, commits to the database and redirects back to /admin.
    Aborts with 400 if validation fails or the keyword already exists.
    """
    keyword = (request.form.get("keyword") or "").strip()
    title = (request.form.get("title") or "").strip() or None
    url = (request.form.get("url") or "").strip()

    if not keyword or not url:
        abort(400, "Keyword and URL required")

    db = get_db()
    init_db()
    ensure_lists_schema(db)
    try:
        db.execute("INSERT INTO links(keyword, url, title) VALUES (?, ?, ?)", (keyword, url, title))
        db.commit()
    except Exception:
        abort(400, f"Keyword '{keyword}' already exists")
    return redirect("/admin")


@admin_bp.route("/delete", methods=["POST"])
def admin_delete():
    """Delete an existing link by keyword.

    Expects form field:
        - keyword (required)

    On success, removes the link and redirects to /admin.
    Aborts with 400 if keyword is missing.
    """
    keyword = (request.form.get("keyword") or "").strip()
    if not keyword:
        abort(400, "Keyword required")
    db = get_db()
    db.execute("DELETE FROM links WHERE lower(keyword) = lower(?)", (keyword,))
    db.commit()
    return redirect("/admin")


@admin_bp.route("/list-add", methods=["POST"])
def admin_list_add():
    """Create a new list and a corresponding shortcut link.

    Expects form fields:
        - name (optional if slug provided)
        - slug (optional; generated from name if missing)
        - description (optional)

    Behavior:
        - Creates the list record (slug, name, description).
        - Adds a link with the same slug pointing to /lists/<slug>.
        - Redirects back to /admin.
    Aborts with 400 if both name and slug are missing or slug already exists.
    """
    db = get_db()
    ensure_lists_schema(db)
    name = (request.form.get("name") or "").strip()
    slug = (request.form.get("slug") or "").strip()
    desc = (request.form.get("description") or "").strip() or None
    if not name and not slug:
        abort(400, "name or slug required")
    if not slug:
        slug = to_slug(name)
    if not name:
        name = slug.replace("-", " ").title()
    try:
        db.execute("INSERT INTO lists(slug, name, description) VALUES (?, ?, ?)", (slug, name, desc))
        db.commit()
    except Exception:
        abort(400, f"List '{slug}' already exists")

    base_url = request.host_url.rstrip("/")
    list_url = f"{base_url}/lists/{slug}"
    title = f"List - {name}"

    try:
        db.execute("INSERT INTO links(keyword, url, title) VALUES (?, ?, ?)", (slug, list_url, title))
        db.commit()
    except Exception:
        pass

    return redirect("/admin")


@admin_bp.route("/set-lists", methods=["POST"])
def admin_set_lists():
    """Update a link's associated lists (CSV of slugs).

    Expects form fields:
        - keyword (required)
        - slugs (CSV string, optional)

    Behavior:
        - Auto-creates any missing lists using pretty names.
        - Replaces existing associations for the link with the provided set.
        - Redirects back to /admin.
    Aborts with 404 if the link is not found.
    """
    db = get_db()
    ensure_lists_schema(db)
    keyword = (request.form.get("keyword") or "").strip()
    slugs_raw = (request.form.get("slugs") or "").strip()

    link = db.execute("SELECT id FROM links WHERE lower(keyword)=lower(?)", (keyword,)).fetchone()
    if not link:
        abort(404, "link not found")
    link_id = link["id"]

    slugs = [s.strip().lower() for s in slugs_raw.split(",") if s.strip()]
    slugs = sorted(set(slugs))

    for slug in slugs:
        row = db.execute("SELECT id FROM lists WHERE slug=?", (slug,)).fetchone()
        if not row:
            name = slug.replace("-", " ").title()
            db.execute("INSERT INTO lists(slug, name) VALUES (?, ?)", (slug, name))
    db.commit()

    db.execute("DELETE FROM link_lists WHERE link_id=?", (link_id,))
    for slug in slugs:
        list_id = db.execute("SELECT id FROM lists WHERE slug=?", (slug,)).fetchone()["id"]
        db.execute("INSERT OR IGNORE INTO link_lists(link_id, list_id) VALUES (?, ?)", (link_id, list_id))
    db.commit()
    return redirect("/admin")


@admin_bp.route("/list-delete", methods=["POST"])
def admin_list_delete():
    """Delete a list by slug and redirect to the lists index.

    Expects form field:
        - slug (required)

    Behavior:
        - Removes the list row (cascades through link_lists).
        - Redirects to /lists after deletion.
    Aborts with 400 if slug is missing, or 404 if the list doesn't exist.
    """
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
