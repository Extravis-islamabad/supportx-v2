"""Assets module (WP-049; architecture.md §2.11, §6.1; parity 07; D-141): IT and non-IT assets.

- Session 1, the catalogue: product types in a tree (IT or non-IT, D-141), products with price
  and tax apart, states with a fixed category, life cycles and their moves, and the asset
  settings. Each tenant gets the Appendix A defaults the first time its catalogue is used.
- Session 2, the asset record: tags from patterns, unique tag and serial, custom fields,
  search, history, live lists, the trash. Only IT assets that are not disposed count toward the
  plan's asset limit (D-141).
- Sessions 3-5 add the life cycle in use, ownership and loans.
- WP-049b session 1: consumable stock with batches, allocations and the ledger, minimum-stock
  rules, bookings ahead (handed over as loans, from the portal when allowed), and the loan's
  display ID, department, site and register filters.
- WP-049b session 2: cost lines and total cost of ownership, depreciation and book value
  (`assets.view_financials`), cost centre and GL code, notes and attachments on the asset,
  history with filters.

Licensed with the `assets` feature. Public interface for other modules: `can_see`, `asset_refs`
and `assets_of` (REQ-AST-025, for work items), and the disposal guard port.
"""

from fastapi import FastAPI

from app.core.authorization import ALL_SCOPES, PermissionSpec, Scope
from app.core.modules import ModuleSpec
from app.modules.assets.api.financials import router as financials_router
from app.modules.assets.api.records import router as records_router
from app.modules.assets.api.routes import router
from app.modules.assets.api.stock import router as stock_router
from app.modules.assets.events import EVENTS
from app.modules.assets.service import notifications, reporting
from app.modules.assets.service.assets import (
    EDIT_DISPOSED,
    VIEW_FINANCIALS,
    assets_naming_vendor,
    count_managed_assets,
)
from app.modules.assets.service.catalogue import CONFIGURE, MANAGE, REINSTATE, VIEW
from app.modules.assets.service.consumables import (
    DraftPurchaseRequests,
    register_draft_purchase_requests,
    unregister_draft_purchase_requests,
)
from app.modules.assets.service.disposals import register_disposal_guard, unregister_disposal_guard
from app.modules.assets.service.file_access import FILE_ACCESS
from app.modules.assets.service.loans import loan_sweep, on_loan_guard
from app.modules.assets.service.ownership import OWNER_SITE_CHANGED
from app.modules.assets.service.realtime import CHANNELS, ROUTES
from app.modules.assets.service.refs import (
    AssetRef,
    asset_refs,
    assets_of,
    can_see,
    email_includes_assets,
)
from app.modules.assets.service.valuations import valuation_sweep
from app.modules.procurement import register_vendor_usage
from app.shared.files.ports import register_owner_access, unregister_owner_access
from app.shared.schedules import ScheduleSpec

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
    # Changing a disposed asset (REQ-AST-017 AC3): admins only by default (coordinator, 2026-11-06).
    PermissionSpec(EDIT_DISPOSED, FEATURE, _NOT_OWN),
    PermissionSpec(CONFIGURE, FEATURE),
    # Costs, depreciation and book value (WP-049b s2, REQ-AST-036/037): the asset manager's and
    # the administrators' (coordinator, 2026-11-11); custom roles may add it. One scope: it
    # shows the money of the assets its holder may see anyway (assets.view's scope decides).
    PermissionSpec(VIEW_FINANCIALS, FEATURE, defaults=(("asset_manager", "all"),)),
)

# Assets name vendors: a vendor they still name cannot be deleted (procurement asks).
register_vendor_usage(assets_naming_vendor)
# Assets in the reports library, with their states, product types and products named (lane C's
# P6 review): at import, so the consumers worker that runs report exports has them too.
reporting.register()


async def _startup(app: FastAPI) -> None:
    del app
    register_owner_access(FILE_ACCESS)


async def _shutdown(app: FastAPI) -> None:
    del app
    unregister_owner_access(FILE_ACCESS.owner_types)


module = ModuleSpec(
    name="assets",
    # The catalogue first: its fixed paths (/assets/states ...) must match before /assets/{id}.
    # Stock and bookings (WP-049b) before the record too: /assets/consumables is not an ID.
    routers=[router, stock_router, financials_router, records_router],
    events=EVENTS,
    feature=FEATURE,
    permissions=PERMISSIONS,
    channels=CHANNELS,
    realtime=ROUTES,
    # Only IT assets that are not disposed use a slot of the plan's limit (D-141).
    usage_counters={"assets": count_managed_assets},
    # A person's site changed: assets that follow their owner move too (REQ-AST-018 AC2).
    consumers=[OWNER_SITE_CHANGED],
    # Loan due and overdue, and warranty notices (REQ-AST-059), claimed once per tenant.
    schedules=[
        ScheduleSpec("assets__notices", 60, loan_sweep),
        # Book values move with time (REQ-AST-037): each asset is valued once a day for reports;
        # hourly, so a day is never missed (each run values only what is not valued today).
        ScheduleSpec("assets__valuations", 3600, valuation_sweep),
    ],
    on_startup=[_startup],
    on_shutdown=[_shutdown],
)

# Disposal certificates (REQ-AST-017): at import, for the workers too; startup registers again
# after a shutdown (tests start and stop the app), as knowledge does.
register_owner_access(FILE_ACCESS)
# An asset on loan is not disposed of (REQ-AST-017 AC1).
register_disposal_guard(on_loan_guard)
# Acknowledgements notify through the engine (REQ-AST-023): at import, for the workers too.
notifications.register()

__all__ = [
    "AssetRef",
    "DraftPurchaseRequests",
    "asset_refs",
    "assets_of",
    "can_see",
    "email_includes_assets",
    "module",
    "register_disposal_guard",
    "register_draft_purchase_requests",
    "unregister_disposal_guard",
    "unregister_draft_purchase_requests",
]
