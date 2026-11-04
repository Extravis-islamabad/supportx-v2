"""Assets module (WP-049; architecture.md §2.11, §6.1; parity 07; D-141): IT and non-IT assets.

Session 1: the catalogue. Product types in a tree (IT or non-IT, D-141), products with price
and tax apart, states with a fixed category, life cycles and their moves, and the asset
settings. Each tenant gets the Appendix A defaults the first time its catalogue is used.
Licensed with the `assets` feature. Sessions 2-5 add the asset record, the life cycle in use,
ownership and loans; the managed-asset usage counter (only IT assets count, D-141) comes with
the asset record in session 2.

Public interface for other modules: none yet.
"""

from app.core.authorization import ALL_SCOPES, PermissionSpec, Scope
from app.core.modules import ModuleSpec
from app.modules.assets.api.routes import router
from app.modules.assets.events import EVENTS
from app.modules.assets.service.catalogue import CONFIGURE, MANAGE, REINSTATE, VIEW
from app.modules.assets.service.realtime import ROUTES

FEATURE = "assets"
_NOT_OWN: tuple[Scope, ...] = ("all", "site", "group")

# Moved here from identity_access's reserved list (WP-049a). The system roles' grants of
# assets.view and assets.manage stay where they are (identity_access/domain/permissions.py).
# Reinstating a retired asset (Appendix A: "retired → in stock (permission)") and the catalogue
# are for admins and custom roles until the product owner says otherwise.
PERMISSIONS = (
    PermissionSpec(VIEW, FEATURE, ALL_SCOPES),
    PermissionSpec(MANAGE, FEATURE, _NOT_OWN),
    PermissionSpec(REINSTATE, FEATURE, _NOT_OWN),
    PermissionSpec(CONFIGURE, FEATURE),
)

module = ModuleSpec(
    name="assets",
    routers=[router],
    events=EVENTS,
    feature=FEATURE,
    permissions=PERMISSIONS,
    realtime=ROUTES,
)

__all__ = ["module"]
