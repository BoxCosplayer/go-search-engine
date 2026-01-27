from flask import Blueprint

from .. import utils  # re-exported for tests that monkeypatch admin.utils
from ..utils import _discover_config_path  # re-exported for tests and callers
from .auth import require_admin_auth

admin_bp = Blueprint("admin", __name__)


@admin_bp.before_request
def _guard_admin():
    return require_admin_auth()


# Import route modules to register handlers with the blueprint.
from . import config_routes, home, links, lists, users  # noqa

# Re-export route callables for backwards compatibility.
admin_home = home.admin_home
admin_config = config_routes.admin_config
admin_add = links.admin_add
admin_delete = links.admin_delete
admin_update = links.admin_update
admin_list_add = lists.admin_list_add
admin_set_lists = lists.admin_set_lists
admin_list_delete = lists.admin_list_delete
admin_users = users.admin_users
admin_users_add = users.admin_users_add
admin_users_password = users.admin_users_password
admin_users_toggle = users.admin_users_toggle
admin_users_delete = users.admin_users_delete

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
    "admin_users",
    "admin_users_add",
    "admin_users_password",
    "admin_users_toggle",
    "admin_users_delete",
]
