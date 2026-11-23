"""Per-person list settings, saved views and favourites (WP-049b s4a): see service.py.

Public interface: `ListSpec`, `register_list`, `unregister_list`, `list_spec`, and the service
functions the `system` module's routes call. The table is `list_settings` (migration 0140).
"""

from app.shared.list_settings.domain import ALL, CUSTOM, custom_key, saved_view_id
from app.shared.list_settings.service import (
    ListSpec,
    create_saved_view,
    delete_saved_view,
    list_spec,
    register_list,
    save_view_setting,
    settings_of,
    unregister_list,
    update_saved_view,
    view_setting,
)

__all__ = [
    "ALL",
    "CUSTOM",
    "ListSpec",
    "create_saved_view",
    "custom_key",
    "delete_saved_view",
    "list_spec",
    "register_list",
    "save_view_setting",
    "saved_view_id",
    "settings_of",
    "unregister_list",
    "update_saved_view",
    "view_setting",
]
