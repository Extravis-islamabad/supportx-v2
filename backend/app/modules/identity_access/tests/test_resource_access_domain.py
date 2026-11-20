"""Fine-grained access compile, per role and narrow-only (ADR-053 §2; D-172). Pure, no I/O."""

import uuid
from types import MappingProxyType

from app.core.authorization import Scope
from app.modules.identity_access.domain import resource_access as rules
from app.modules.identity_access.domain.permissions import Catalogue
from app.modules.identity_access.domain.policy import Grant, compile_subject

ROLE_A = uuid.UUID(int=1)
ROLE_B = uuid.UUID(int=2)
UNRELATED = uuid.UUID(int=3)
PRINTERS = {"type_ids": [str(uuid.UUID(int=10))]}
SERVERS = {"type_ids": [str(uuid.UUID(int=11))]}


def _grants(permission: str, scope: Scope) -> rules.RoleGrants:
    """One role holding one permission at one scope."""
    return MappingProxyType({permission: ((scope, None),)})


def test_no_rule_means_not_narrowed() -> None:
    access = rules.compile_access({ROLE_A: _grants("cmdb.view", "all")}, [])
    assert rules.narrowing(access, "ci") is None


def test_each_role_keeps_its_own_scope_and_its_own_rules() -> None:
    """The coordinator's case: A sees all with printers only, B sees site S1 with servers only.

    The person's reach is (A's all and printers) or (B's site and servers): never servers elsewhere.
    """
    access = rules.compile_access(
        {ROLE_A: _grants("cmdb.view", "all"), ROLE_B: _grants("cmdb.view", "site")},
        [(ROLE_A, "ci", PRINTERS), (ROLE_B, "ci", SERVERS)],
    )
    reaches = rules.narrowing(access, "ci")
    assert reaches is not None
    by_scope = {r.grants["cmdb.view"][0][0]: r.rules for r in reaches}
    assert by_scope["all"] == (MappingProxyType({"type_ids": tuple(PRINTERS["type_ids"])}),)
    assert by_scope["site"] == (MappingProxyType({"type_ids": tuple(SERVERS["type_ids"])}),)


def test_a_role_without_a_rule_keeps_only_its_own_scope() -> None:
    """A role with no rule shows its whole scope, and no more: it never lifts another role's."""
    access = rules.compile_access(
        {ROLE_A: _grants("cmdb.view", "site"), ROLE_B: _grants("cmdb.view", "all")},
        [(ROLE_B, "ci", PRINTERS)],
    )
    reaches = rules.narrowing(access, "ci")
    assert reaches is not None  # still narrowed: B's "all" is printers only
    by_scope = {r.grants["cmdb.view"][0][0]: r.rules for r in reaches}
    assert by_scope["site"] is None  # A: its site scope, whole
    assert by_scope["all"] is not None  # B: everywhere, printers only


def test_a_role_that_never_sees_cis_has_no_say() -> None:
    access = rules.compile_access(
        {ROLE_A: _grants("cmdb.view", "all"), UNRELATED: _grants("incidents.view", "all")},
        [(ROLE_A, "ci", PRINTERS)],
    )
    reaches = rules.narrowing(access, "ci")
    assert reaches is not None
    assert len(reaches) == 1
    assert rules.narrowing(access, "asset") is None


def test_the_cache_form_round_trips_and_an_unknown_form_is_refused() -> None:
    access = rules.compile_access(
        {ROLE_A: _grants("cmdb.view", "all"), ROLE_B: _grants("cmdb.view", "site")},
        [(ROLE_A, "ci", PRINTERS)],
    )
    assert rules.to_json(rules.from_json(rules.to_json(access))) == rules.to_json(access)
    assert rules.from_json(None) == rules.EMPTY
    try:
        rules.from_json({"ci": [{"site_ids": ["x"]}]})
    except ValueError:
        pass
    else:
        msg = "an unknown cache form must never read as not narrowed"
        raise AssertionError(msg)


def test_a_tenant_admin_is_never_narrowed() -> None:
    access = rules.compile_access({ROLE_A: _grants("cmdb.view", "all")}, [(ROLE_A, "ci", PRINTERS)])
    admin = compile_subject(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role_keys={"tenant_admin"},
        grants=[("cmdb.view", Grant("all"))],
        catalogue=Catalogue({}),
        entitled_features=frozenset(),
        is_tenant_admin=True,
        resources=access,
    )
    assert admin.resource_access == rules.EMPTY


def test_criteria_are_checked_against_the_registered_ones() -> None:
    allowed = {"type_ids": "ids", "criticality_max": "ceiling"}
    assert rules.criteria_problems({}, allowed) == ["criteria_required"]
    assert rules.criteria_problems({"colour": ["x"]}, allowed) == ["criterion_unknown:colour"]
    assert rules.criteria_problems({"type_ids": ["not-an-id"]}, allowed) == [
        "criterion_invalid:type_ids"
    ]
    assert rules.criteria_problems({"type_ids": []}, allowed) == ["criterion_invalid:type_ids"]
    assert rules.criteria_problems(PRINTERS, allowed) == []
    assert rules.criteria_problems({"criticality_max": "high"}, allowed) == []
