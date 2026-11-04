"""E-mailed approval links without sign-in (D-132; lane B's conditions and review points).

Real PostgreSQL with RLS. Anonymous calls on the tenant's own address: the token stands for its
recipient. Opening never acts; one use; 72 hours; a rejection needs a reason; the tenant's
"require sign-in for approvals" takes effect at once, also for links already sent; another
tenant's address finds nothing; a link the step no longer needs is spent; refused uses are
capped; no token in any log line.
"""

import uuid
from datetime import timedelta
from typing import Any

import pytest
import structlog.testing
from sqlalchemy import select

from app.core.tenancy import TenantContext
from app.modules.work_items.infra.models import WorkItemApproval
from app.modules.work_items.service.approvals import issue_links
from app.shared.action_links.domain import MAX_FAILED_USES
from tests.app_state import set_state
from tests.db.test_approvals_api import approvals, decide, fresh, manager_of, waiting
from tests.db.test_branding_api import slug_of
from tests.db.test_incidents_api import CONSOLE, Org, World, problem, world

__all__ = ["world"]  # the fixture, re-used

PUBLIC = "/api/v1/public/action-links"
BASE = "links.test"


@pytest.fixture
def addressed(world: World, monkeypatch: pytest.MonkeyPatch) -> World:
    """The world, with tenants reachable at <slug>.links.test."""
    settings = world.app.state.settings.model_copy(update={"tenant_base_domain": BASE})
    set_state(monkeypatch, world.app.state, "settings", settings)
    return world


async def host(world: World, org: Org) -> dict[str, str]:
    return {"Host": f"{await slug_of(world, org)}.{BASE}"}


async def token_for(world: World, org: Org, record: dict[str, Any]) -> str:
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        rows = list(
            await session.scalars(
                select(WorkItemApproval).where(
                    WorkItemApproval.work_item_id == uuid.UUID(record["id"])
                )
            )
        )
        tokens = await issue_links(session, rows)
    return next(iter(tokens.values()))


async def anonymous(world: World, org: Org, path: str, **body: Any) -> Any:  # noqa: ANN401 - JSON
    return await world.client.post(f"{PUBLIC}/{path}", json=body, headers=await host(world, org))


async def two_approvers_waiting(world: World, org: Org) -> dict[str, Any]:
    from tests.db.test_approval_notifications import two_approvers  # noqa: PLC0415 - shared setup

    return await two_approvers(world, org)


async def test_opening_never_acts_and_one_use_decides(addressed: World) -> None:
    world = addressed
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    token = await token_for(world, a, record)
    for _ in range(2):  # a scanner and the person: neither peek decides anything
        seen = await anonymous(world, a, "peek", token=token)
        assert seen.status_code == 200, seen.text
        assert seen.headers["Referrer-Policy"] == "no-referrer"
    assert (await fresh(world, a, record))["approval_status"] == "pending"
    for method in ("GET", "HEAD"):
        assert (
            await world.client.request(method, f"{PUBLIC}/use", headers=await host(world, a))
        ).status_code == 405
    used = await anonymous(world, a, "use", token=token, body={"decision": "approve"})
    assert used.status_code == 200, used.text
    assert (await fresh(world, a, record))["approval_status"] == "approved"
    [entry] = await approvals(world, a, a.admin, record)
    assert (entry["decided_by"], entry["channel"]) == (str(a.tech_a), "email_link")
    audit = await world.sql(
        "SELECT actor_id, outcome FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        a.tenant,
        "action_link.used",
    )
    assert [(r["actor_id"], r["outcome"]) for r in audit] == [(a.tech_a, "done")]
    again = await anonymous(world, a, "use", token=token, body={"decision": "reject"})
    assert problem(again) == (404, "action_link_not_found")  # used: as unknown (lane B)
    wrong = await anonymous(world, a, "use", token="B" * 43, body={"decision": "approve"})
    assert problem(wrong) == (404, "action_link_not_found")


async def test_a_rejection_needs_a_reason_and_a_link_lasts_72_hours(addressed: World) -> None:
    world = addressed
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    token = await token_for(world, a, record)
    [row] = await world.sql(
        "SELECT expires_at - created_at AS ttl FROM action_links WHERE tenant_id = $1", a.tenant
    )
    assert abs(row["ttl"] - timedelta(hours=72)) < timedelta(seconds=1)  # app and DB clocks
    bare = await anonymous(world, a, "use", token=token, body={"decision": "reject"})
    assert bare.status_code == 422, bare.text
    assert bare.json()["errors"][0]["code"] == "reason_required"
    assert (await fresh(world, a, record))["approval_status"] == "pending"  # not consumed
    await world.sql(
        "UPDATE action_links SET expires_at = now() - interval '1 second' WHERE tenant_id = $1",
        a.tenant,
    )
    late = await anonymous(
        world, a, "use", token=token, body={"decision": "reject", "comment": "No"}
    )
    assert problem(late) == (409, "action_link_expired")


async def test_the_sign_in_setting_forces_the_signed_in_path_at_once(addressed: World) -> None:
    """Also for links already sent (lane B point 8); the signed-in route still works."""
    world = addressed
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    token = await token_for(world, a, record)
    settings = await world.call("GET", "/service-requests/settings", a, a.admin)
    on = await world.call(
        "PATCH",
        "/service-requests/settings",
        a,
        a.admin,
        json={"approvals_require_sign_in": True},
        headers={"If-Match": settings.headers["ETag"], **CONSOLE},
    )
    assert on.status_code == 200, on.text
    for path in ("peek", "use"):
        refused = await anonymous(world, a, path, token=token, body={"decision": "approve"})
        assert problem(refused) == (403, "action_link_sign_in_required"), path
    signed = await world.call(
        "POST",
        "/action-links/use",
        a,
        a.tech_a,
        json={"token": token, "body": {"decision": "approve"}},
        headers=CONSOLE,
    )
    assert signed.status_code == 200, signed.text


async def test_another_tenants_address_finds_nothing(addressed: World) -> None:
    world = addressed
    a, b = world.a, world.b
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    token = await token_for(world, a, record)
    foreign = await anonymous(world, b, "peek", token=token)
    assert problem(foreign) == (404, "action_link_not_found")
    nowhere = await world.client.post(
        f"{PUBLIC}/peek", json={"token": token}, headers={"Host": f"nobody.{BASE}"}
    )
    assert problem(nowhere) == (404, "action_link_not_found")


async def test_a_step_decided_by_a_colleague_spends_the_link(addressed: World) -> None:
    world = addressed
    a = world.a
    record = await two_approvers_waiting(world, a)
    tokens: dict[uuid.UUID, str] = {}
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        rows = list(
            await session.scalars(
                select(WorkItemApproval).where(
                    WorkItemApproval.work_item_id == uuid.UUID(record["id"])
                )
            )
        )
        made = await issue_links(session, rows)
        tokens = {r.approver_id: made[r.id] for r in rows if r.approver_id}
    entries = await approvals(world, a, a.tech_b, record)
    mine = next(e for e in entries if e["approver_id"] == str(a.tech_b))
    assert (await decide(world, a, a.tech_b, record, mine, "approve")).status_code == 200
    spent = await anonymous(world, a, "use", token=tokens[a.tech_a], body={"decision": "approve"})
    assert problem(spent) == (409, "action_link_revoked")  # "no longer needed", never a 500


async def test_refused_uses_are_capped_and_never_log_the_token(addressed: World) -> None:
    world = addressed
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    token = await token_for(world, a, record)
    await world.sql(
        "UPDATE work_item_type_settings SET approvals_require_sign_in = true"
        " WHERE tenant_id = $1 AND type = 'service_request'",
        a.tenant,
    )
    with structlog.testing.capture_logs() as logs:
        for _ in range(MAX_FAILED_USES):
            refused = await anonymous(world, a, "use", token=token, body={"decision": "approve"})
            assert problem(refused)[0] == 403
    await world.sql(
        "UPDATE work_item_type_settings SET approvals_require_sign_in = false"
        " WHERE tenant_id = $1 AND type = 'service_request'",
        a.tenant,
    )
    capped = await anonymous(world, a, "use", token=token, body={"decision": "approve"})
    assert problem(capped) == (409, "action_link_revoked")
    refusals = await world.sql(
        "SELECT actor_id, outcome, reason_code, details FROM audit_entries"
        " WHERE tenant_id = $1 AND action = 'action_link.used' AND outcome = 'refused'",
        a.tenant,
    )
    assert len(refusals) == MAX_FAILED_USES + 1
    assert not any(token in str(r["details"]) for r in refusals)
    assert not any(token in str(entry) for entry in logs)
