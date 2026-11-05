"""Assets module (WP-049; architecture.md §2.11, §6.1; parity 07; D-141): IT and non-IT assets.

- Session 1, the catalogue: product types in a tree (IT or non-IT, D-141), products with price
  and tax apart, states with a fixed category, life cycles and their moves, and the asset
  settings. Each tenant gets the Appendix A defaults the first time its catalogue is used.
- Session 2, the asset record: tags from patterns, unique tag and serial, custom fields,
  search, history, live lists, the trash. Only IT assets that are not disposed count toward the
  plan's asset limit (D-141).
- Sessions 3-5 add the life cycle in use, ownership and loans.

Licensed with the `assets` feature. Public interface for other modules: none yet.
"""

from app.core.authorization import ALL_SCOPES, PermissionSpec, Scope
from app.core.modules import ModuleSpec
from app.modules.assets.api.records import router as records_router
from app.modules.assets.api.routes import router
from app.modules.assets.events import EVENTS
from app.modules.assets.service.assets import assets_naming_vendor, count_managed_assets
from app.modules.assets.service.catalogue import CONFIGURE, MANAGE, REINSTATE, VIEW
from app.modules.assets.service.realtime import CHANNELS, ROUTES
from app.modules.procurement import register_vendor_usage

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

# Assets name vendors: a vendor they still name cannot be deleted (procurement asks).
register_vendor_usage(assets_naming_vendor)

module = ModuleSpec(
    name="assets",
    # The catalogue first: its fixed paths (/assets/states ...) must match before /assets/{id}.
    routers=[router, records_router],
    events=EVENTS,
    feature=FEATURE,
    permissions=PERMISSIONS,
    channels=CHANNELS,
    realtime=ROUTES,
    # Only IT assets that are not disposed use a slot of the plan's limit (D-141).
    usage_counters={"assets": count_managed_assets},
)

__all__ = ["module"]
