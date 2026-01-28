from flask import Blueprint, abort, render_template

from ..db import get_db

lists_bp = Blueprint("lists", __name__)


@lists_bp.route("/")
def index():
    """Render the Lists index page.

    Shows all lists with their name, optional description, and the number of
    links in each list.

    Returns:
        A rendered HTML page (lists/index.html) with a "lists" collection.
    """
    db = get_db()
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
    """Render a single list page.

    Args:
        slug: The list slug to display.

    Behavior:
        - Looks up the list by slug (case-insensitive).
        - Shows all links associated with that list.
        - Returns 404 if the list does not exist.

    Returns:
        A rendered HTML page (lists/view.html) with "list" metadata and its "rows".
    """
    db = get_db()
    info = db.execute(
        "SELECT id, slug, name, description FROM lists WHERE slug COLLATE NOCASE = ?",
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
