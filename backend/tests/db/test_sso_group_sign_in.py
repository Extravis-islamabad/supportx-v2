"""A brokered sign-in follows its identity provider's groups (WP-057 S5c-1b; REQ-SEC-014).

- Following on, `seen` set: the sign-in's groups are read and cleared, then followed. The role
  the group maps to is held, managed, and the attributes are gone from the person.
- `seen` absent (a concurrent sign-in took them, or none ran): no change, the role kept.
- G2: seen and no overage, but no groups sent: the person is in no group now, the role goes.
- The admin API failing at the read and clear: the sign-in is refused, nothing applied.
- Following off, or another tenant's alias: nothing is read.

The fake identity provider and real PostgreSQL of test_auth_bff.py, with the shared FakeAdmin.
"""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import asyncpg

from app.modules.identity_access.domain import sso
from tests.db import test_auth_bff
from tests.db.test_auth_bff import Bff

pytestmark = test_auth_bff.pytestmark
bff = test_auth_bff.bff  # the BFF world fixture, reused


async def _sql(bff: Bff, statement: str, *args: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        return await conn.fetch(statement, *args)
    finally:
        await conn.close()


@dataclass
class Following:
    tenant: uuid.UUID
    alias: str
    provider: uuid.UUID
    role: uuid.UUID
    admin: Any  # tests.db.test_identity_api.FakeAdmin


@asynccontextmanager
async def _following(bff: Bff, *, follow: bool = True) -> AsyncIterator[Following]:
    """Tenant a's own provider following `groups`, `sx-change` onto a role; the fake admin."""
    from tests.db.test_identity_api import FakeAdmin  # noqa: PLC0415 - shared fake

    tenant = bff.tenants[0]
    alias = f"sx-a-{uuid.uuid4().hex[:6]}"
    provider, role = uuid.uuid4(), uuid.uuid4()
    settings = {"groups": {"follow": follow, "claim": "groups"}}
    await _sql(
        bff,
        "INSERT INTO sso_providers (id, tenant_id, alias, protocol, preset, display_name, state,"
        " settings) VALUES ($1, $2, $3, 'oidc', 'entra', 'Acme', 'on', $4::jsonb)",
        provider, tenant, alias, json.dumps(settings),
    )  # fmt: skip
    await _sql(
        bff,
        "INSERT INTO roles (id, tenant_id, key, name) VALUES ($1, $2, $3, 'Change reviewers')",
        role, tenant, f"r_{uuid.uuid4().hex[:8]}",
    )  # fmt: skip
    await _sql(
        bff,
        "INSERT INTO idp_group_mappings (id, tenant_id, source_kind, source_id, external_group_id,"
        " role_id) VALUES ($1, $2, 'sso', $3, 'sx-change', $4)",
        uuid.uuid4(), tenant, provider, role,
    )  # fmt: skip
    auth = bff.app.state.auth
    before = auth.identity_admin
    admin = FakeAdmin()
    auth.identity_admin = admin
    try:
        yield Following(tenant, alias, provider, role, admin)
    finally:
        auth.identity_admin = before


def _sent(alias: str, *, groups: list[str] | None, seen: bool = True) -> dict[str, list[str]]:
    names = sso.group_attributes(alias)
    found: dict[str, list[str]] = {}
    if groups is not None:
        found[names.groups] = groups
    if seen:
        found[names.seen] = ["1"]
    return found


async def _holds(bff: Bff, tenant: uuid.UUID, email: str, role: uuid.UUID) -> list[bool]:
    rows = await _sql(
        bff,
        "SELECT ur.managed FROM user_roles ur JOIN users u ON u.id = ur.user_id"
        " WHERE ur.tenant_id = $1 AND u.email = $2 AND ur.role_id = $3",
        tenant, email, role,
    )  # fmt: skip
    return [r["managed"] for r in rows]


async def test_a_sign_in_follows_its_groups_read_once_and_cleared(bff: Bff) -> None:
    async with _following(bff) as world:
        email = f"g-{uuid.uuid4().hex[:6]}@demo.test"
        user = bff.user("a", email=email, identity_provider=world.alias)
        world.admin.attributes[user.subject] = _sent(world.alias, groups=["sx-change", "other"])
        signed = await bff.login(user)
        assert signed.status_code == 302, signed.text
        assert await _holds(bff, world.tenant, email, world.role) == [True]  # managed
        names = sso.group_attributes(world.alias)
        assert world.admin.took == [(user.subject, names.all())]
        assert world.admin.attributes[user.subject] == {}  # read and cleared

        # The next sign-in found nothing it set (seen absent): no change, the role is kept.
        again = await bff.login(user)
        assert again.status_code == 302, again.text
        assert await _holds(bff, world.tenant, email, world.role) == [True]

        # G2: seen and no overage, no groups sent: in no group now, the role goes.
        world.admin.attributes[user.subject] = _sent(world.alias, groups=None)
        last = await bff.login(user)
        assert last.status_code == 302, last.text
        assert await _holds(bff, world.tenant, email, world.role) == []


async def test_an_overage_changes_nothing(bff: Bff) -> None:
    async with _following(bff) as world:
        email = f"o-{uuid.uuid4().hex[:6]}@demo.test"
        user = bff.user("a", email=email, identity_provider=world.alias)
        world.admin.attributes[user.subject] = _sent(world.alias, groups=["sx-change"])
        assert (await bff.login(user)).status_code == 302
        names = sso.group_attributes(world.alias)
        world.admin.attributes[user.subject] = {
            **_sent(world.alias, groups=[]),
            names.overage: ['{"groups": "src1"}'],
        }
        assert (await bff.login(user)).status_code == 302
        assert await _holds(bff, world.tenant, email, world.role) == [True]  # untouched


async def test_the_admin_api_failing_refuses_the_sign_in_with_nothing_applied(bff: Bff) -> None:
    async with _following(bff) as world:
        email = f"f-{uuid.uuid4().hex[:6]}@demo.test"
        user = bff.user("a", email=email, identity_provider=world.alias)
        world.admin.attributes[user.subject] = _sent(world.alias, groups=["sx-change"])
        world.admin.fail_take = True
        refused = await bff.login(user)
        # An API client gets the problem (a browser, the same code on its return address).
        assert (refused.status_code, refused.json()["code"]) == (403, "idp_groups_unavailable")
        assert await _holds(bff, world.tenant, email, world.role) == []
        assert (await bff.me()).status_code == 401  # no session


async def test_nothing_is_read_when_following_is_off(bff: Bff) -> None:
    async with _following(bff, follow=False) as world:
        email = f"n-{uuid.uuid4().hex[:6]}@demo.test"
        user = bff.user("a", email=email, identity_provider=world.alias)
        world.admin.attributes[user.subject] = _sent(world.alias, groups=["sx-change"])
        assert (await bff.login(user)).status_code == 302
        assert world.admin.took == []
