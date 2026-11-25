"""CMDB module (WP-053; architecture.md §2.12, §6.1): configuration items.

Session 1, the foundation (REQ-CMDB-001..005, 031, 024's write side): CI types in a tree, CI
states (active or end of life), CIs, copy, type change, the trash, CIs made from assets, a picker
that leaves end-of-life CIs out, and a snapshot after every save (`cmdb_ci_versions`). Custom
fields come through the metadata module in a follow-up (§6.6), never a second system here.

Session 2 (REQ-CMDB-006..009, 024's view side; 0180): relationship types (a name per direction,
rules, impact), relationships (edit rights on both ends), the neighbour map with restricted
placeholders, business views, and a CI's versions as of a time and compared.

Licensed with the `cmdb` feature. Public interface for other modules: `can_see`, `ci_refs`
(`CiRef`), the picker route, and `register_open_counts` (`OpenCounts`, `OpenCountsPort`): the
port work_items registers in S5 for open ticket counts on map nodes. The erasure port moves
owned CIs and business views to the successor.

Session 3b (REQ-CMDB-010, 011, 030): `impact_of` (`Impact`, `ImpactCi`, `ImpactService`,
`AffectedUsers`, `ImpactDirection`), the one impact service every module calls, with CIs the
reader may not see as placeholders.

Session 4a (REQ-CMDB-015, 016; 0191): each attribute's source and time, which source wins (the
tenant's order), and sync rules from assets: preview as the author, runs on demand, hourly and
when an asset changes, written by the sync identity through the CI save path.

Session 4b (REQ-CMDB-017, 018; 0192): merge duplicate CIs (aliases that open the survivor for a
reader who may see it), and import CIs and relationships from CSV or Excel. `register_ci_links`
(`CiLinksPort`): the port work items registers with `work_item_cis` (lane A, S5) to move their CI
links on a merge (IDs only).
"""

from app.core.authorization import ALL_SCOPES, PermissionSpec, Scope
from app.core.modules import ModuleSpec
from app.modules.cmdb.api.baseline_routes import router as baseline_router
from app.modules.cmdb.api.downtime_routes import router as downtime_router
from app.modules.cmdb.api.graph_routes import router as graph_router
from app.modules.cmdb.api.merge_routes import router as merge_router
from app.modules.cmdb.api.routes import router
from app.modules.cmdb.api.sync_routes import router as sync_router
from app.modules.cmdb.domain.impact import ImpactDirection
from app.modules.cmdb.events import EVENTS
from app.modules.cmdb.service import access_criteria as _access_criteria
from app.modules.cmdb.service import automation as _automation
from app.modules.cmdb.service import field_catalogue as _field_catalogue
from app.modules.cmdb.service import notifications as _notifications
from app.modules.cmdb.service import person_data as _person_data
from app.modules.cmdb.service import person_mentions as _person_mentions
from app.modules.cmdb.service import reporting as _reporting
from app.modules.cmdb.service import type_tree as _type_tree
from app.modules.cmdb.service.approver_owners import Owner, owners_of
from app.modules.cmdb.service.catalogue import (
    ADD,
    CONFIGURE,
    DELETE,
    EDIT,
    MANAGE,
    RECORD_DOWNTIME,
    VIEW,
)
from app.modules.cmdb.service.downtimes import on_downtime_changed, run_downtime_states
from app.modules.cmdb.service.impact import (
    AffectedUsers,
    Impact,
    ImpactCi,
    ImpactService,
    impact_of,
)
from app.modules.cmdb.service.imports import run_cmdb_imports
from app.modules.cmdb.service.links import CiLinksPort, register_ci_links
from app.modules.cmdb.service.open_counts import (
    LINKED_TYPES,
    Count,
    OpenCounts,
    OpenCountsPort,
    register_open_counts,
)
from app.modules.cmdb.service.realtime import CHANNELS, ROUTES
from app.modules.cmdb.service.refs import CiRef, can_link, can_see, ci_refs, visible_ci_ids
from app.modules.cmdb.service.sync import on_asset_changed, run_sync_rules
from app.shared.events import ConsumerSpec
from app.shared.schedules import ScheduleSpec

FEATURE = "cmdb"
_ASSET_MANAGER: tuple[tuple[str, Scope], ...] = (("asset_manager", "all"),)
# A downtime by hand on a CI (S5b): those who run the desk and those who keep the CIs.
_DOWNTIME_RECORDERS: tuple[tuple[str, Scope], ...] = (
    ("service_desk_manager", "all"),
    ("asset_manager", "all"),
)

# Plain role scopes (D-172): all, the person's own sites (the CI's site), own groups (its owning
# or managing group) and own (they own it), on Professional too; only the later custom rule
# builder (`fine_grained_access`) is Enterprise.
# cmdb.view and cmdb.manage moved here from identity_access's reserved list (WP-053 S1) with their
# keys unchanged (view gains `own`; every saved scope stays valid), so saved grants need no
# mapping. The system roles' grants of them stay in identity_access/domain/permissions.py.
# cmdb.manage covers add, edit and delete; the finer rights are for custom roles, and the asset
# manager gets them too.
PERMISSIONS = (
    PermissionSpec(VIEW, FEATURE, ALL_SCOPES),
    PermissionSpec(ADD, FEATURE, defaults=_ASSET_MANAGER),
    PermissionSpec(EDIT, FEATURE, ALL_SCOPES, defaults=_ASSET_MANAGER),
    PermissionSpec(DELETE, FEATURE, ALL_SCOPES, defaults=_ASSET_MANAGER),
    PermissionSpec(MANAGE, FEATURE),
    PermissionSpec(RECORD_DOWNTIME, FEATURE, ALL_SCOPES, defaults=_DOWNTIME_RECORDERS),
    # The type tree, the states and the settings: admins and custom roles.
    PermissionSpec(CONFIGURE, FEATURE),
)

module = ModuleSpec(
    name="cmdb",
    # The sync routes first: /cmdb/sync-rules is not under /cmdb/cis/{id}, but keep fixed paths
    # ahead of the parameterised ones as the other modules do.
    routers=[sync_router, router, graph_router, merge_router, downtime_router, baseline_router],
    events=EVENTS,
    feature=FEATURE,
    permissions=PERMISSIONS,
    channels=CHANNELS,
    realtime=ROUTES,
    # S4a: an asset changed → its ID on each enabled sync rule's next incremental run (IDs only).
    consumers=[
        ConsumerSpec(
            name="cmdb__asset_sync",
            event_types=("assets.asset.changed",),
            handler=on_asset_changed,
        ),
        # S5b: a work item's downtime onto each CI it names (REQ-CMDB-020; lane A's event).
        ConsumerSpec(
            name="cmdb__downtimes",
            event_types=("work_items.downtime.changed",),
            handler=on_downtime_changed,
        ),
    ],
    # Queued, hourly and incremental sync runs, claimed once per tenant (S4a); queued imports (S4b).
    schedules=[
        ScheduleSpec("cmdb__sync_runs", 30, run_sync_rules),
        ScheduleSpec("cmdb__imports", 5, run_cmdb_imports),
        # S5b: downtimes become active and completed as time passes (REQ-CMDB-020 AC1).
        ScheduleSpec("cmdb__downtime_states", 60, run_downtime_states),
    ],
)

# GDPR erasure (ADR-052): owned CIs move to the successor; at import, for the workers too.
_person_data.register()
_person_mentions.register()  # the mentions report and redaction (ADR-052 S1b; 0176)
_type_tree.register()  # custom fields scoped to a CI type subtree (0175 part 2)
_field_catalogue.register()  # CI custom fields an admin may restrict per role (ADR-047)
_access_criteria.register()  # what fine-grained access rules may narrow CIs to (ADR-053)
_reporting.register()  # CIs and relationships for reports and dashboards (REQ-CMDB-032, S5a)
_automation.register()  # CIs as trigger sources and targets (WP-053 S5d)
_notifications.register()  # a CI's state change, to its owner and groups (S5d)

__all__ = [
    "LINKED_TYPES",
    "AffectedUsers",
    "CiLinksPort",
    "CiRef",
    "Count",
    "Impact",
    "ImpactCi",
    "ImpactDirection",
    "ImpactService",
    "OpenCounts",
    "OpenCountsPort",
    "Owner",
    "can_link",
    "can_see",
    "ci_refs",
    "impact_of",
    "module",
    "owners_of",
    "register_ci_links",
    "register_open_counts",
    "visible_ci_ids",
]
