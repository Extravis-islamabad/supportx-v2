"""Policy domain without I/O: catalogue, system-role matrix, scopes, rules, delegation (WP-016)."""

import uuid
from types import MappingProxyType

import pytest

from app.core.authorization import PermissionSpec, Scope
from app.modules.identity_access.domain.permissions import (
    IDENTITY_PERMISSIONS,
    RESERVED_PERMISSIONS,
    Catalogue,
    CatalogueError,
    covers,
)
from app.modules.identity_access.domain.policy import (
    Grant,
    RecordFacts,
    Subject,
    can_delegate,
    compile_subject,
    decide,
    matches,
)

ORG = (
    PermissionSpec("sites.view"),
    PermissionSpec("sites.manage"),
    PermissionSpec("groups.view"),
    PermissionSpec("groups.manage"),
    PermissionSpec("settings.manage"),
    PermissionSpec("licence.manage"),
)
FEATURES = frozenset({"incident", "problem", "change", "release", "assets", "cmdb", "knowledge"})
CATALOGUE = Catalogue.build([*IDENTITY_PERMISSIONS, *RESERVED_PERMISSIONS, *ORG], FEATURES)
TENANT, ME, OTHER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
SITE, GROUP = uuid.uuid4(), uuid.uuid4()


def subject_for(*roles: str, features: frozenset[str] = FEATURES, **extra: object) -> Subject:
    grants = [(p, Grant(s)) for role in roles for p, s in CATALOGUE.system_grants(role)]
    return compile_subject(
        tenant_id=TENANT,
        user_id=ME,
        role_keys=roles,
        grants=grants,
        catalogue=CATALOGUE,
        entitled_features=features,
        is_tenant_admin="tenant_admin" in roles,
        **extra,  # type: ignore[arg-type]  # site_ids / group_ids in tests
    )


# --- the system-role matrix ----------------------------------------------------------------------

MATRIX = {
    #                      admin  tech   requester
    "users.view": (True, True, False),
    "users.manage": (True, False, False),
    "roles.view": (True, False, False),
    "roles.manage": (True, False, False),
    "profile.edit": (True, True, True),
    "settings.manage": (True, False, False),
    "licence.manage": (True, False, False),
    "requests.view": (True, True, True),
    "requests.create": (True, True, True),
    "requests.assign": (True, True, False),
    "changes.approve": (True, False, False),
    "problems.manage": (True, True, False),
    "knowledge.view": (True, True, True),
    "knowledge.manage": (True, True, False),
}


@pytest.mark.parametrize("permission", sorted(MATRIX))
def test_system_role_matrix(permission: str) -> None:
    expected = MATRIX[permission]
    actual = tuple(
        subject_for(role).holds(permission) for role in ("tenant_admin", "technician", "requester")
    )
    assert actual == expected


def test_scopes_of_system_roles() -> None:
    assert subject_for("tenant_admin").broadest_scope("requests.view") == "all"
    assert subject_for("technician").broadest_scope("problems.manage") == "group"
    assert subject_for("requester").broadest_scope("requests.view") == "own"
    assert subject_for("requester").broadest_scope("users.view") is None


def test_tenant_admin_gets_new_catalogue_permissions_automatically() -> None:
    bigger = Catalogue.build(
        [*CATALOGUE.permissions.values(), PermissionSpec("tickets.export")], FEATURES
    )
    assert ("tickets.export", "all") in bigger.system_grants("tenant_admin")


def test_permissions_of_features_outside_the_plan_are_never_held() -> None:
    essentials = frozenset({"incident", "knowledge"})
    admin = subject_for("tenant_admin", features=essentials)
    assert not admin.holds("changes.approve")
    assert admin.check("changes.approve").reason == "not_entitled"
    assert admin.holds("requests.view")
    assert admin.holds("users.manage")  # core permissions need no feature
    assert subject_for("tenant_admin").check("nope.nothing").reason == "no_permission"


# --- catalogue validation -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec",
    [
        PermissionSpec("Users.View"),
        PermissionSpec("users"),
        PermissionSpec("users.view"),  # duplicate
        PermissionSpec("x.y", scopes=()),
        PermissionSpec("x.y", feature="teleport"),
    ],
)
def test_bad_permission_declarations_stop_startup(spec: PermissionSpec) -> None:
    with pytest.raises(CatalogueError):
        Catalogue.build([*CATALOGUE.permissions.values(), spec], FEATURES)


# --- scopes, conditions, decisions ----------------------------------------------------------------


def test_scope_coverage() -> None:
    assert covers("all", "own")
    # Own records can be outside the user's sites and groups: no covering between them.
    assert not covers("site", "own")
    assert not covers("group", "own")
    assert not covers("site", "group")
    assert not covers("own", "site")
    assert not covers("group", "all")


def custom(
    *grants: tuple[str, Grant],
    sites: frozenset[uuid.UUID] = frozenset(),
    groups: frozenset[uuid.UUID] = frozenset(),
) -> Subject:
    return compile_subject(
        tenant_id=TENANT,
        user_id=ME,
        role_keys=["custom"],
        grants=grants,
        catalogue=CATALOGUE,
        entitled_features=FEATURES,
        site_ids=sites,
        group_ids=groups,
    )


@pytest.mark.parametrize(
    ("scope", "record", "allowed"),
    [
        ("own", RecordFacts(owner_ids=frozenset({ME})), True),
        ("own", RecordFacts(owner_ids=frozenset({OTHER})), False),
        ("site", RecordFacts(site_id=SITE), True),
        ("site", RecordFacts(site_id=uuid.uuid4()), False),
        ("group", RecordFacts(group_id=GROUP), True),
        ("group", RecordFacts(group_id=None), False),
        ("all", RecordFacts(), True),
    ],
)
def test_each_scope_reaches_exactly_its_records(
    scope: Scope, record: RecordFacts, allowed: bool
) -> None:
    subject = custom(
        ("requests.view", Grant(scope)), sites=frozenset({SITE}), groups=frozenset({GROUP})
    )
    decision = decide(subject, "requests.view", record)
    assert decision.allowed is allowed
    assert decision.reason == ("allowed" if allowed else "out_of_scope")


def test_attribute_condition() -> None:
    hr_only = {"field": "category", "op": "eq", "value": "hr"}
    subject = custom(("requests.view", Grant("all", hr_only)))
    assert decide(subject, "requests.view", RecordFacts(attributes={"category": "hr"}))
    refused = decide(subject, "requests.view", RecordFacts(attributes={"category": "it"}))
    assert refused.reason == "condition_not_met"


def test_unconditioned_grant_makes_narrower_ones_redundant() -> None:
    subject = custom(
        ("requests.view", Grant("own")),
        ("requests.view", Grant("all")),
        ("requests.view", Grant("site", {"field": "category", "op": "eq", "value": "hr"})),
    )
    assert subject.grants["requests.view"] == (Grant("all"),)


def test_invalid_scopes_and_unknown_permissions_are_dropped() -> None:
    subject = custom(("profile.edit", Grant("all")), ("ghost.view", Grant("all")))
    assert subject.grants == MappingProxyType({})


@pytest.mark.parametrize(
    ("condition", "attributes", "expected"),
    [
        ({"field": "title", "op": "contains", "value": "VPN"}, {"title": "my vpn is down"}, True),
        ({"field": "title", "op": "starts_with", "value": "my"}, {"title": "My laptop"}, True),
        ({"field": "category", "op": "ne", "value": "hr"}, {"category": None}, True),
        ({"field": "category", "op": "not_in", "value": ["hr"]}, {"category": None}, True),
        ({"field": "category", "op": "in", "value": ["hr", "it"]}, {"category": "it"}, True),
        ({"field": "priority", "op": "gte", "value": 3}, {"priority": 2}, False),
        ({"field": "priority", "op": "between", "value": [1, 3]}, {"priority": 2}, True),
        ({"field": "closed_at", "op": "is_null"}, {"closed_at": None}, True),
        ({"field": "created_at", "op": "today"}, {"created_at": "2026-10-23"}, False),  # needs SQL
        (
            {
                "or": [
                    {"field": "a", "op": "eq", "value": 1},
                    {"field": "b", "op": "eq", "value": 2},
                ]
            },
            {"b": 2},
            True,
        ),
        (
            {
                "and": [
                    {"field": "a", "op": "eq", "value": 1},
                    {"field": "b", "op": "eq", "value": 2},
                ]
            },
            {"b": 2},
            False,
        ),
    ],
)
def test_in_memory_rule_semantics(
    condition: dict[str, object], attributes: dict[str, object], expected: bool
) -> None:
    assert matches(condition, attributes) is expected


# --- delegation: no privilege escalation ----------------------------------------------------------


def test_delegation_never_exceeds_what_you_hold() -> None:
    hr = {"field": "category", "op": "eq", "value": "hr"}
    manager = custom(
        ("requests.view", Grant("site")),
        ("requests.edit", Grant("all", hr)),
        ("roles.manage", Grant("all")),
    )
    assert can_delegate(manager, "requests.view", "site", None)
    assert not can_delegate(manager, "requests.view", "own", None)  # different records
    assert not can_delegate(manager, "requests.view", "all", None)
    assert not can_delegate(manager, "requests.view", "group", None)
    assert can_delegate(manager, "requests.edit", "group", hr)
    assert not can_delegate(manager, "requests.edit", "all", None)  # dropping the condition
    assert not can_delegate(manager, "users.manage", "all", None)
    assert can_delegate(subject_for("tenant_admin"), "users.manage", "all", None)


def test_subject_cache_round_trip() -> None:
    subject = custom(
        ("requests.view", Grant("site", {"field": "category", "op": "eq", "value": "hr"})),
        sites=frozenset({SITE}),
        groups=frozenset({GROUP}),
    )
    assert Subject.from_dict(subject.to_dict()) == subject
