"""Signed one-time action links over HTTP (WP-030 s3; REQ-NTF-024, REQ-SR-026; lane B's
five conditions). Real PostgreSQL with RLS; the approval engine's links as the first user.
"""

import uuid
from typing import Any

from sqlalchemy import select, text

from app.core.tenancy import TenantContext
from app.modules.work_items.infra.models import WorkItemApproval
from app.modules.work_items.service.approvals import issue_links
from tests.db.test_approvals_api import approvals, fresh, manager_of, waiting
from tests.db.test_incidents_api import CONSOLE, Org, World, problem, world

__all__ = ["world"]  # the fixture, re-used

LINKS = "/action-links"


async def link_for(world: World, org: Org, record: dict[str, Any]) -> str:
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        rows = list(
            await session.scalars(
                select(WorkItemApproval).where(
                    WorkItemApproval.work_item_id == uuid.UUID(record["id"])
                )
            )
        )
        tokens = await issue_links(session, rows)
    [token] = tokens.values()
    return token


async def post(world: World, org: Org, user: uuid.UUID, path: str, **body: Any) -> Any:  # noqa: ANN401 - JSON
    return await world.call("POST", f"{LINKS}/{path}", org, user, json=body, headers=CONSOLE)


async def test_the_approver_peeks_then_decides_once(world: World) -> None:
    """Conditions 1, 2 and 4: peek never acts; use acts once; audited; never stored in clear."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    token = await link_for(world, a, record)
    stored = await world.sql("SELECT token_digest FROM action_links WHERE tenant_id = $1", a.tenant)
    assert [len(r["token_digest"]) for r in stored] == [32]
    assert token.encode() not in bytes(stored[0]["token_digest"])

    seen = await post(world, a, a.tech_a, "peek", token=token)
    assert seen.status_code == 200, seen.text
    assert seen.headers["Referrer-Policy"] == "no-referrer"
    assert seen.json()["summary"]["display_id"] == record["display_id"]
    assert (await fresh(world, a, record))["approval_status"] == "pending"  # peek never acts

    used = await post(world, a, a.tech_a, "use", token=token, body={"decision": "approve"})
    assert used.status_code == 200, used.text
    assert (await fresh(world, a, record))["approval_status"] == "approved"
    [entry] = await approvals(world, a, a.admin, record)
    assert entry["channel"] == "email_link"
    again = await post(world, a, a.tech_a, "use", token=token, body={"decision": "reject"})
    assert problem(again) == (409, "action_link_used")
    audit = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        a.tenant,
        "action_link.used",
    )
    assert audit[0]["n"] >= 1


async def test_only_its_recipient_and_only_while_it_stands(world: World) -> None:
    """Conditions 2 and 5: someone else, a forged token, a withdrawn request: nothing happens."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    token = await link_for(world, a, record)
    other = await post(world, a, a.tech_b, "use", token=token, body={"decision": "approve"})
    assert problem(other) == (403, "action_link_wrong_recipient")
    forged = await post(world, a, a.tech_a, "peek", token="A" * 43)
    assert problem(forged) == (404, "action_link_not_found")
    short = await post(world, a, a.tech_a, "peek", token="A" * 10)
    assert short.status_code == 422
    withdrawn = await world.call(
        "POST",
        f"/service-requests/{record['id']}/withdraw",
        a,
        a.requester,
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    late = await post(world, a, a.tech_a, "peek", token=token)
    assert problem(late) == (409, "action_link_revoked")  # REQ-SR-061 AC2: no longer needed
    bad = await post(world, a, a.tech_a, "use", token=token, body={"decision": "maybe"})
    assert problem(bad)[0] == 409  # the link's own state first, never the body


async def test_a_link_needs_a_signed_in_person(world: World) -> None:
    """Plan D7 interim default: no sign-in, no action."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    token = await link_for(world, a, record)
    anonymous = await world.client.post(f"/api/v1{LINKS}/peek", json={"token": token})
    assert anonymous.status_code in {401, 403}, anonymous.text


async def test_action_links_are_isolated_by_rls(world: World) -> None:
    """CLAUDE.md rule a: another tenant neither finds nor changes them, even with the token."""
    a, b = world.a, world.b
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    token = await link_for(world, a, record)
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert (await session.execute(text("SELECT id FROM action_links"))).all() == []
        changed = await session.execute(text("UPDATE action_links SET used_at = now()"))
        assert changed.rowcount == 0
    foreign = await post(world, b, b.admin, "peek", token=token)
    assert problem(foreign) == (404, "action_link_not_found")
