from flask import render_template, request
from werkzeug.exceptions import HTTPException

from ..db import ensure_lists_schema, get_db
from . import admin_bp


def _render_admin_home(error_message: str | None = None):
    """Render the Admin home page with optional error messaging."""
    db = get_db()
    ensure_lists_schema(db)
    rows = db.execute(
        """
        SELECT l.id, l.keyword, l.title, l.url, l.search_enabled,
               IFNULL(GROUP_CONCAT(li.slug, ', '), '') AS lists_csv
        FROM links l
        LEFT JOIN link_lists ll ON ll.link_id = l.id
        LEFT JOIN lists li ON li.id = ll.list_id
        GROUP BY l.id
        ORDER BY l.keyword COLLATE NOCASE
        """
    ).fetchall()

    edit_key = (request.args.get("edit") or "").strip()
    edit_row = None
    if edit_key:
        edit_row = db.execute(
            "SELECT keyword, title, url, search_enabled FROM links WHERE lower(keyword)=lower(?)",
            (edit_key,),
        ).fetchone()

    all_lists = db.execute("SELECT slug, name FROM lists ORDER BY name COLLATE NOCASE").fetchall()
    return render_template(
        "admin/index.html",
        rows=rows,
        all_lists=all_lists,
        edit_row=dict(edit_row) if edit_row else None,
        error_message=error_message,
    )


def admin_error(message: str, status_code: int = 400):
    """Return the admin home page with a surfaced error message."""
    return _render_admin_home(error_message=message), status_code


@admin_bp.errorhandler(HTTPException)
def _handle_admin_http_error(err):
    return admin_error(err.description or err.name, err.code)


@admin_bp.route("/")
def admin_home():
    """Render the Admin home page."""
    return _render_admin_home()
