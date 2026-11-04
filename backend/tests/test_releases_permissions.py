"""releases.* moves from identity's reserved list into the release type (WP-058a s1).

Lane B's conditions on #214: the technician keeps exactly identity's releases.view grant at
`all` (nothing widened), requesters get no release key, releases.manage leaves the catalogue
(saved custom roles are mapped by migration 0091), and the tenant admin holds every release key.
"""

from app.core.modules import ModuleRegistry, discover_modules
from app.modules.identity_access import build_catalogue
from app.modules.work_items.domain.types import RELEASE
from app.modules.work_items.service.access import permissions


def _release_grants(role: str, technician_scope: str) -> set[tuple[str, str]]:
    catalogue = build_catalogue(ModuleRegistry(discover_modules()))
    return {
        (key, scope)
        for key, scope in catalogue.system_grants(role, technician_scope=technician_scope)  # type: ignore[arg-type]  # a scope literal
        if key.startswith("releases.")
    }


def test_technicians_keep_only_view_and_requesters_get_nothing() -> None:
    for technician_scope in ("group", "all"):
        assert _release_grants("technician", technician_scope) == {("releases.view", "all")}
        assert _release_grants("requester", technician_scope) == set()


def test_the_tenant_admin_holds_every_release_key_at_all() -> None:
    keys = {p.key for p in permissions(RELEASE)}
    assert _release_grants("tenant_admin", "group") == {(k, "all") for k in keys}


def test_manage_is_gone_and_view_keeps_every_scope() -> None:
    catalogue = build_catalogue(ModuleRegistry(discover_modules()))
    assert catalogue.get("releases.manage") is None
    view = catalogue.get("releases.view")
    assert view is not None
    assert set(view.scopes) == {"all", "site", "group", "own"}
    assert view.scopes[0] == "all"
