"""Managed access follows how the person signed in (WP-057 S5c-1b; D-188, strict).

The cast: one person (a requester, who holds neither permission below on their own) with
- a role from an SSO mapping of this tenant's provider (`changes.view`),
- a role from a directory mapping (`problems.view`),
- a support group membership from the SSO mapping (group scope is access: lane B's (a)).

| session | SSO role | directory role | SSO group |
|---|---|---|---|
| SSO through this tenant's provider | yes | yes | yes |
| password (or no sign-in) | no | yes | no |
| SSO with another alias (a tenant switch) | no | yes | no |
| break-glass | no | no | no |
| "could act" (notices) | yes | yes | yes |

And: one compile per source in the Valkey cache (a password session never reads the SSO
session's subject), and organization's port leaves out a managed membership it doesn't admit
while keeping hand-made ones.

Real PostgreSQL and Valkey on the incident world: every organisation is new (rule 5h).
"""

import uuid

import pytest

from app.core.tenancy import ANY_SOURCE, NO_SIGN_IN, AccessSource, AccessSourceKind, TenantContext
from app.modules.identity_access.domain.group_mappings import SourceKind
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.service import group_mappings
from app.modules.organization import memberships
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_group_mappings_api import _directory
from tests.db.test_incidents_api import Org, World, make_org, role

pytestmark = [pytest.mark.db, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

SSO_RIGHT, DIRECTORY_RIGHT = "changes.view", "problems.view"


class Cast:
    """The organisation, its provider's alias and the person whose access is mapped."""

    def __init__(self, org: Org, alias: str, person: uuid.UUID) -> None:
        self.org, self.alias, self.person = org, alias, person


async def _mapping(
    world: World, org: Org, kind: str, source: uuid.UUID, group: str, **target: uuid.UUID
) -> None:
    column, value = next(iter(target.items()))
    await world.sql(
        f"INSERT INTO idp_group_mappings (id, tenant_id, source_kind, source_id,"  # noqa: S608 - the column is one of two names in this file
        f" external_group_id, {column}) VALUES ($1, $2, $3, $4, $5, $6)",
        uuid.uuid4(), org.tenant, kind, source, group, value,
    )  # fmt: skip


async def _cast(world: World) -> Cast:
    org = await make_org(world, f"Scoped {uuid.uuid4().hex[:6]}")
    alias = f"sx-scoped-{uuid.uuid4().hex[:8]}"
    provider = uuid.uuid4()
    await world.sql(
        "INSERT INTO sso_providers (id, tenant_id, alias, protocol, preset, display_name)"
        " VALUES ($1, $2, $3, 'oidc', 'entra', 'Acme sign-in')",
        provider, org.tenant, alias,
    )  # fmt: skip
    directory = await _directory(world, org)
    sso_role = await role(world, org, f"Changes {uuid.uuid4().hex[:6]}", [(SSO_RIGHT, "all")])
    dir_role = await role(
        world, org, f"Problems {uuid.uuid4().hex[:6]}", [(DIRECTORY_RIGHT, "all")]
    )
    await _mapping(world, org, "sso", provider, "sx-change", role_id=sso_role)
    await _mapping(world, org, "sso", provider, "sx-desk", group_id=org.gb)
    await _mapping(world, org, "directory", directory, "dir-problem", role_id=dir_role)
    person = org.requester2
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        await group_mappings.follow(
            session, source_kind=SourceKind.SSO, source_id=provider,
            user_id=person, group_ids=frozenset({"sx-change", "sx-desk"}),
        )  # fmt: skip
        await group_mappings.follow(
            session, source_kind=SourceKind.DIRECTORY, source_id=directory,
            user_id=person, group_ids=frozenset({"dir-problem"}),
        )  # fmt: skip
    return Cast(org, alias, person)


async def _compiled(world: World, cast: Cast, source: AccessSource) -> Subject:
    policy = world.app.state.policy
    async with world.app.state.db.tenant_session(TenantContext(cast.org.tenant)) as session:
        compiled: Subject = await policy.compile(
            session, cast.org.tenant, cast.person, source=source
        )
    return compiled


def _sees(subject: Subject) -> tuple[bool, bool, bool]:
    return subject.holds(SSO_RIGHT), subject.holds(DIRECTORY_RIGHT), bool(subject.group_ids)


async def test_each_sign_in_admits_its_own_managed_access(world: World) -> None:
    cast = await _cast(world)
    sso = AccessSource(AccessSourceKind.SSO, cast.alias)
    elsewhere = AccessSource(AccessSourceKind.SSO, "sx-another-tenants-provider")
    assert _sees(await _compiled(world, cast, sso)) == (True, True, True)
    assert _sees(await _compiled(world, cast, AccessSource(AccessSourceKind.PASSWORD))) == (
        False,
        True,
        False,
    )
    assert _sees(await _compiled(world, cast, NO_SIGN_IN)) == (False, True, False)
    assert _sees(await _compiled(world, cast, elsewhere)) == (False, True, False)
    assert _sees(await _compiled(world, cast, AccessSource(AccessSourceKind.BREAK_GLASS))) == (
        False,
        False,
        False,
    )
    assert _sees(await _compiled(world, cast, ANY_SOURCE)) == (True, True, True)


async def test_a_password_session_never_reads_the_sso_sessions_cached_subject(
    world: World,
) -> None:
    cast = await _cast(world)
    policy = world.app.state.policy
    tenant, person = cast.org.tenant, cast.person
    sso = AccessSource(AccessSourceKind.SSO, cast.alias)
    password = AccessSource(AccessSourceKind.PASSWORD)
    first = await policy.subject(tenant, person, source=sso)  # compiled and cached
    assert first.holds(SSO_RIGHT)
    again = await policy.subject(tenant, person, source=password)
    assert not again.holds(SSO_RIGHT)  # its own compile, never the SSO session's
    assert (await policy.subject(tenant, person, source=sso)).holds(SSO_RIGHT)


async def test_organizations_port_leaves_out_a_managed_membership_it_does_not_admit(
    world: World,
) -> None:
    cast = await _cast(world)
    async with world.app.state.db.tenant_session(TenantContext(cast.org.tenant)) as session:
        everyone = await memberships(session, cast.person)
        none_admitted = await memberships(session, cast.person, admitted_managed=frozenset())
        admitted = await memberships(
            session, cast.person, admitted_managed=frozenset({cast.org.gb})
        )
    assert cast.org.gb in everyone.group_ids  # routing: every membership
    assert cast.org.gb not in none_admitted.group_ids
    assert cast.org.gb in admitted.group_ids


async def test_the_profile_lists_what_only_another_sign_in_applies(world: World) -> None:
    """Lane B's Q3: self only, names only, empty never 404; SSO through that provider lists none."""
    cast = await _cast(world)
    listed = await world.call("GET", "/identity/my-access/elsewhere", cast.org, cast.person)
    assert listed.status_code == 200, listed.text
    found = {(i["kind"], i["provider_name"]) for i in listed.json()}
    assert found == {("role", "Acme sign-in"), ("group", "Acme sign-in")}
    assert all(i["name"] for i in listed.json())  # named, never a bare ID
    # Someone with nothing from a sign-in group: an empty list, not a 404.
    nobody = await world.call("GET", "/identity/my-access/elsewhere", cast.org, cast.org.tech_a)
    assert (nobody.status_code, nobody.json()) == (200, [])
    async with world.app.state.db.tenant_session(TenantContext(cast.org.tenant)) as session:
        through = await group_mappings.held_elsewhere(
            session, cast.person, AccessSource(AccessSourceKind.SSO, cast.alias)
        )
    assert through == []


async def test_a_refusal_says_the_right_comes_from_a_sign_in_group(world: World) -> None:
    """Lane B's condition 4: a job or a password session refused says why, never "no permission"."""
    from app.core.errors import PermissionDenied  # noqa: PLC0415 - this test only
    from app.modules.identity_access.service.policy import SIGN_IN_GROUP_ONLY  # noqa: PLC0415

    cast = await _cast(world)
    strict = await _compiled(world, cast, NO_SIGN_IN)
    assert SSO_RIGHT in strict.held_elsewhere
    assert DIRECTORY_RIGHT not in strict.held_elsewhere  # it applies here
    with pytest.raises(PermissionDenied) as refused:
        world.app.state.policy.require(strict, [SSO_RIGHT])
    assert refused.value.params["reason"] == SIGN_IN_GROUP_ONLY
    through = await _compiled(world, cast, AccessSource(AccessSourceKind.SSO, cast.alias))
    assert through.held_elsewhere == frozenset()  # nothing left out
