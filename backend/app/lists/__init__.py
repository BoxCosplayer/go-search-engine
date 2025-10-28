from flask import Blueprint, abort, render_template

from ..db import ensure_lists_schema, get_db

lists_bp = Blueprint("lists", __name__)


@lists_bp.route("/")
def index():
    db = get_db()
    ensure_lists_schema(db)
    rows = db.execute(
        """
        SELECT li.slug, li.name, li.description, COUNT(ll.link_id) AS count
        FROM lists li
        LEFT JOIN link_lists ll ON ll.list_id = li.id
        GROUP BY li.id
        ORDER BY li.name COLLATE NOCASE
        """
    ).fetchall()
    return render_template("lists/index.html", lists=rows)


@lists_bp.route("/<slug>")
def view(slug):
    db = get_db()
    ensure_lists_schema(db)
    info = db.execute(
        "SELECT id, slug, name, description FROM lists WHERE lower(slug)=lower(?)",
        (slug,),
    ).fetchone()
    if not info:
        abort(404, "list not found")
    rows = db.execute(
        """
        SELECT l.keyword, l.title, l.url
        FROM links l
        JOIN link_lists ll ON ll.link_id = l.id
        WHERE ll.list_id = ?
        ORDER BY l.keyword COLLATE NOCASE
        """,
        (info["id"],),
    ).fetchall()
    return render_template("lists/view.html", list=info, rows=rows)
