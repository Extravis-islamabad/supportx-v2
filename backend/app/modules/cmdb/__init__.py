"""CMDB module (WP-053; architecture.md §2.12, §6.1): configuration items.

Session 1, the foundation (REQ-CMDB-001..005, 031, 024's write side): CI types in a tree, CI
states (active or end of life), CIs, copy, type change, the trash, CIs made from assets, a picker
that leaves end-of-life CIs out, and a snapshot after every save (`cmdb_ci_versions`). Custom
fields come through the metadata module in a follow-up (§6.6), never a second system here.

Licensed with the `cmdb` feature. Public interface for other modules: `can_see`, `ci_refs`
(`CiRef`) and the picker route. The erasure port moves owned CIs to the successor.
"""

from app.core.authorization import ALL_SCOPES, PermissionSpec, Scope
from app.core.modules import ModuleSpec
from app.modules.cmdb.api.routes import router
from app.modules.cmdb.events import EVENTS
from app.modules.cmdb.service import person_data as _person_data
from app.modules.cmdb.service import person_mentions as _person_mentions
from app.modules.cmdb.service.catalogue import ADD, CONFIGURE, DELETE, EDIT, MANAGE, VIEW
from app.modules.cmdb.service.realtime import CHANNELS, ROUTES
from app.modules.cmdb.service.refs import CiRef, can_link, can_see, ci_refs

FEATURE = "cmdb"
_ASSET_MANAGER: tuple[tuple[str, Scope], ...] = (("asset_manager", "all"),)

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
    # The type tree, the states and the settings: admins and custom roles.
    PermissionSpec(CONFIGURE, FEATURE),
)

module = ModuleSpec(
    name="cmdb",
    routers=[router],
    events=EVENTS,
    feature=FEATURE,
    permissions=PERMISSIONS,
    channels=CHANNELS,
    realtime=ROUTES,
)

# GDPR erasure (ADR-052): owned CIs move to the successor; at import, for the workers too.
_person_data.register()
_person_mentions.register()  # the mentions report and redaction (ADR-052 S1b; 0176)

__all__ = ["CiRef", "can_link", "can_see", "ci_refs", "module"]
