"""The five requests.* permissions keep their grants when work_items takes them (WP-030 s1).

Lane B's conditions on #182: the requester, technician and tenant admin roles compile to the same
keys at the same scopes for requests.view / create / edit / assign / close before and after the
keys moved from identity's reserved list into the service request type; no data step.
"""

from app.core.modules import ModuleRegistry, discover_modules
from app.modules.identity_access import build_catalogue
from app.modules.licensing.domain.catalogue import EDITION_FEATURES, Feature

FIVE = ("requests.view", "requests.create", "requests.edit", "requests.assign", "requests.close")

PINNED = {
    "requester": {("requests.view", "own"), ("requests.create", "all"), ("requests.close", "own")},
    "technician": {(key, "all") for key in FIVE},
    "tenant_admin": {(key, "all") for key in FIVE},
}


def _grants(role: str, technician_scope: str) -> set[tuple[str, str]]:
    catalogue = build_catalogue(ModuleRegistry(discover_modules()))
    return {
        (key, scope)
        for key, scope in catalogue.system_grants(role, technician_scope=technician_scope)  # type: ignore[arg-type]  # a scope literal
        if key in FIVE
    }


def test_the_five_keys_compile_as_before_for_every_system_role() -> None:
    for technician_scope in ("group", "all"):
        for role, expected in PINNED.items():
            assert _grants(role, technician_scope) == expected, (role, technician_scope)


def test_every_one_of_the_five_keys_is_still_in_the_catalogue() -> None:
    catalogue = build_catalogue(ModuleRegistry(discover_modules()))
    assert all(catalogue.get(key) is not None for key in FIVE)


def test_the_five_keys_allow_exactly_their_old_scopes() -> None:
    catalogue = build_catalogue(ModuleRegistry(discover_modules()))
    every = ("all", "site", "group", "own")
    expected = {
        "requests.view": every,
        "requests.create": ("all",),
        "requests.edit": every,
        "requests.assign": ("all", "site", "group"),  # never "own"
        "requests.close": every,
    }
    for key, scopes in expected.items():
        spec = catalogue.get(key)
        assert spec is not None
        assert set(spec.scopes) == set(scopes), key
        assert spec.scopes[0] == "all", key  # the admin's grant stays "all"


def test_every_edition_with_incidents_has_service_requests() -> None:
    """The five keys' feature is now service_request: no edition may lose them."""
    for edition, features in EDITION_FEATURES.items():
        if Feature.INCIDENT in features:
            assert Feature.SERVICE_REQUEST in features, edition
