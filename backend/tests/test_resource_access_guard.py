"""Guard: every CMDB and asset choke point carries fine-grained access (ADR-053; lane C 6).

A narrowed subject's rules must reach the SQL of each base query other paths build on: the CI
rows (lists, the record, `can_see`, `visible_ci_ids`, neighbours, versions, business views, the
realtime record channel, mention passages) and the asset rows (lists, the record, report rows,
labels, notifications). They all go through `scope_filter` with a resource type declaring
`narrowed_as`; this proves the narrowing lands in each, per role, and that a narrowed resource
whose module never registered criteria shows nothing.

Sources other modules read records through are pinned too: the asset reporting source is the
only CMDB/asset one, and neither module registers an AI source. Adding one makes this fail until
it is listed here with its scope_filter proof (the coordinator, 2026-11-20).
"""

import uuid
from types import MappingProxyType

from sqlalchemy import ClauseElement
from sqlalchemy.dialects import postgresql

from app.core.authorization import Scope
from app.modules.ai.service import conversations, embeddings, records
from app.modules.assets.service.assets import ASSETS, staff_rows
from app.modules.cmdb.service.cis import CIS, visible_rows
from app.modules.identity_access.domain import resource_access as rules
from app.modules.identity_access.domain.policy import Grant, Subject
from app.modules.identity_access.service import resource_access as service
from app.shared.reporting import ports as reporting

TYPE = str(uuid.UUID(int=7))
SITE = str(uuid.UUID(int=8))
OTHER_SITE = str(uuid.UUID(int=9))
ROLE = uuid.UUID(int=1)
OTHER_ROLE = uuid.UUID(int=2)
# The record types cmdb and assets own: an AI source for any of these must be scope-filtered.
OWNED = ("ci", "ci_", "asset", "asset_", "cmdb", "assets")


def _grants(*pairs: tuple[str, Scope]) -> rules.RoleGrants:
    return MappingProxyType({p: ((s, None),) for p, s in pairs})


def _subject(resource_access: rules.Compiled) -> Subject:
    return Subject(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role_keys=frozenset({"custom"}),
        is_tenant_admin=False,
        grants=MappingProxyType({"cmdb.view": (Grant("all"),), "assets.view": (Grant("all"),)}),
        site_ids=frozenset({uuid.UUID(OTHER_SITE)}),
        resource_access=resource_access,
    )


def _narrowed(resource: str, criteria: dict[str, list[str]], permission: str) -> Subject:
    return _subject(
        rules.compile_access({ROLE: _grants((permission, "all"))}, [(ROLE, resource, criteria)])
    )


# SQLAlchemy's PostgreSQL dialect class is untyped; one instance, made once.
_PG = postgresql.dialect()  # type: ignore[no-untyped-call]


def _sql(statement: ClauseElement) -> str:
    return str(statement.compile(dialect=_PG, compile_kwargs={"literal_binds": True}))


def test_both_resource_types_are_narrowed() -> None:
    assert CIS.narrowed_as == "ci"
    assert ASSETS.narrowed_as == "asset"


def test_a_ci_rule_reaches_the_ci_rows() -> None:
    narrowed = _narrowed("ci", {"site_ids": [SITE]}, "cmdb.view")
    assert SITE in _sql(visible_rows(narrowed))
    assert SITE not in _sql(visible_rows(_subject(rules.EMPTY)))


def test_a_ci_type_rule_takes_the_subtree() -> None:
    found = _sql(visible_rows(_narrowed("ci", {"type_ids": [TYPE]}, "cmdb.view")))
    assert "ra_roots" in found  # the recursive subtree
    assert TYPE in found


def test_an_asset_rule_reaches_the_asset_rows() -> None:
    narrowed = _narrowed("asset", {"site_ids": [SITE]}, "assets.view")
    assert SITE in _sql(staff_rows(narrowed))
    assert SITE not in _sql(staff_rows(_subject(rules.EMPTY)))


def test_each_role_is_narrowed_by_its_own_rules_only() -> None:
    """Role A: all, rule site 1. Role B: site scope (its member site 9), no rule.

    The SQL holds A's rule AND A's scope, OR B's own site scope; never A's rule on B's scope.
    """
    access = rules.compile_access(
        {ROLE: _grants(("cmdb.view", "all")), OTHER_ROLE: _grants(("cmdb.view", "site"))},
        [(ROLE, "ci", {"site_ids": [SITE]})],
    )
    found = _sql(visible_rows(_subject(access)))
    assert SITE in found  # A's rule
    assert OTHER_SITE in found  # B's own site scope, whole


def test_an_unregistered_resource_shows_nothing() -> None:
    saved = service._CRITERIA.pop("ci")  # noqa: SLF001 - the registry, put back below
    try:
        found = service.rules_predicate("ci", (MappingProxyType({"site_ids": (SITE,)}),))
        assert "false" in _sql(found).lower()
    finally:
        service._CRITERIA["ci"] = saved  # noqa: SLF001 - the registry, as it was


def test_no_cmdb_or_asset_ai_source_exists_unproven() -> None:
    """None today. A new one must be added here with its scope_filter proof, or this fails."""
    for registry in (
        conversations._SOURCES,  # noqa: SLF001 - the registries themselves
        embeddings._SOURCES,  # noqa: SLF001
        embeddings._LISTERS,  # noqa: SLF001
        records._ACCESS,  # noqa: SLF001
    ):
        owned = [kind for kind in registry if kind.startswith(OWNED)]
        assert owned == [], owned


def test_the_only_cmdb_or_asset_reporting_source_is_the_scoped_one() -> None:
    """The asset source's rows are `staff_rows` (scope_filtered, proven above); none for CIs."""
    owned = [kind for kind in reporting.registered_entities() if kind.startswith(OWNED)]
    assert owned == ["asset"], owned
