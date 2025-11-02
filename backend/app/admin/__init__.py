from flask import Blueprint

from .. import utils  # re-exported for tests that monkeypatch admin.utils
from ..utils import _discover_config_path  # re-exported for tests and callers

# Import route modules to register handlers with the blueprint.
from . import config_routes, home, links, lists  # noqa: F401

admin_bp = Blueprint("admin", __name__)

# Re-export route callables for backwards compatibility.
admin_home = home.admin_home
admin_config = config_routes.admin_config
admin_add = links.admin_add
admin_delete = links.admin_delete
admin_update = links.admin_update
admin_list_add = lists.admin_list_add
admin_set_lists = lists.admin_set_lists
admin_list_delete = lists.admin_list_delete

__all__ = [
    "admin_bp",
    "_discover_config_path",
    "utils",
    "admin_home",
    "admin_config",
    "admin_add",
    "admin_delete",
    "admin_update",
    "admin_list_add",
    "admin_set_lists",
    "admin_list_delete",
]
