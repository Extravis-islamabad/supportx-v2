"""What a vendor support account's grant gives it (WP-057 S4c-2, D-173), against a real database.

- A grant at `view` gives the allow-list's reads, at scope `all`; `view_and_change` adds the work
  and the drafts; neither ever gives a `never` key, nor tenant admin, even with a tenant-admin role
  row put there behind the API (lane B (1), (6)).
- A grant ended, or out of its window, gives nothing; a level changed gives the new level on the
  next compile (lane B (2)).
- The tenant's licence still applies: a feature it lacks gives none of that feature's permissions.
"""

import uuid
from typing import Any

import pytest

from app.core.tenancy import TenantContext
from app.modules.automation.service import workflow_admin
from app.modules.identity_access.domain import support_access
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.events import SupportGrantChanged
from app.modules.identity_access.service import field_access as field_access_service
from app.modules.identity_access.service.authz_consumer import TRIGGERS
from app.modules.identity_access.service.field_access import RuleableField
from app.modules.identity_access.service.policy import PolicyService
from tests.db.test_identity_api import World, world  # noqa: F401 - the fixture, reused
from tests.db.test_support_grants_api import _account, _grant, _sql

pytestmark = pytest.mark.db


async def _compiled(world: World, user_id: uuid.UUID, policy: Any = None) -> Subject:  # noqa: F811, ANN401 - the reused fixture; a PolicyService
    policy = policy or world.app.state.policy
    async with policy.database.tenant_session(TenantContext(world.a.tenant)) as session:
        subject: Subject = await policy.compile(session, world.a.tenant, user_id)
    return subject


async def _support_user(world: World, **changes: Any) -> tuple[str, uuid.UUID]:  # noqa: F811, ANN401 - the reused fixture; JSON
    made = await _grant(world, **changes)
    assert made.status_code == 201, made.text
    grant_id = made.json()["id"]
    _, user_id = await _account(world, grant_id)
    return grant_id, user_id


def _no_never(subject: Subject) -> None:
    for key in subject.grants:
        decision = support_access.SUPPORT_ACCESS.get(key)
        assert decision is not None, key
        assert not isinstance(decision, support_access.Never), key
    assert not subject.is_tenant_admin
    assert subject.role_keys == frozenset()


async def test_view_gives_the_reads_at_scope_all_and_nothing_else(world: World) -> None:  # noqa: F811 - the reused fixture
    _, user_id = await _support_user(world)
    # A tenant-admin role row behind the API's back changes nothing (the compile ceiling).
    (admin_role,) = await _sql(
        world, "SELECT id FROM roles WHERE tenant_id = $1 AND key = 'tenant_admin'", world.a.tenant
    )
    await _sql(
        world,
        "INSERT INTO user_roles (tenant_id, user_id, role_id) VALUES ($1, $2, $3)",
        world.a.tenant,
        user_id,
        admin_role["id"],
    )
    subject = await _compiled(world, user_id)
    _no_never(subject)
    assert subject.grants, "a view grant gives its reads"
    assert set(subject.grants) <= support_access.permissions_for("view")
    assert "incidents.view" in subject.grants
    assert all(g.scope == "all" for g in subject.grants["incidents.view"])
    for refused in ("incidents.edit", "workflows.manage", "users.view", "audit.view"):
        assert refused not in subject.grants, refused


async def test_view_and_change_adds_the_work_and_drafts_never_the_tenants_decisions(
    world: World,  # noqa: F811 - the reused fixture
) -> None:
    _, user_id = await _support_user(
        world, access="view_and_change", change_reason="Fix the stuck workflow on INC-12"
    )
    subject = await _compiled(world, user_id)
    _no_never(subject)
    for given in ("incidents.view", "incidents.edit", "workflows.manage", "sla.manage"):
        assert given in subject.grants, given
    # Tied to its grant, contacts withheld, and the same after the Valkey cache's round trip.
    assert subject.support_grant_id is not None
    assert subject.mask_contacts
    assert Subject.from_dict(subject.to_dict()) == subject
    for refused in (
        "incidents.add_note",  # opens private notes, their files and full notices (lane B)
        "incidents.reply",
        "incidents.approve",
        "incidents.delete",
        "automation.manage",
        "workflows.run",
        "reports.export",
        "api_keys.manage",
        "identity.manage",
    ):
        assert refused not in subject.grants, refused


async def test_an_ended_grant_gives_nothing_and_a_lowered_level_loses_change(
    world: World,  # noqa: F811 - the reused fixture
) -> None:
    grant_id, user_id = await _support_user(
        world, access="view_and_change", change_reason="Fix the stuck workflow on INC-12"
    )
    assert "incidents.edit" in (await _compiled(world, user_id)).grants
    # Lane B (2): the level lowered on a live grant, the next compile has `view` only.
    await _sql(
        world,
        "UPDATE support_grants SET access = 'view' WHERE tenant_id = $1 AND id = $2",
        world.a.tenant,
        uuid.UUID(grant_id),
    )
    lowered = await _compiled(world, user_id)
    assert "incidents.view" in lowered.grants
    assert "incidents.edit" not in lowered.grants
    # Out of its window: nothing.
    await _sql(
        world,
        "UPDATE support_grants SET starts_at = now() + interval '1 hour',"
        " ends_at = now() + interval '2 hours' WHERE tenant_id = $1 AND id = $2",
        world.a.tenant,
        uuid.UUID(grant_id),
    )
    assert (await _compiled(world, user_id)).grants == {}
    # Ended: nothing.
    await _sql(
        world,
        "UPDATE support_grants SET starts_at = now() - interval '1 hour',"
        " ends_at = now() + interval '1 hour' WHERE tenant_id = $1 AND id = $2",
        world.a.tenant,
        uuid.UUID(grant_id),
    )
    assert (await _compiled(world, user_id)).grants
    ended = await world.call("POST", f"/identity/vendor-support/grants/{grant_id}/revoke", world.a)
    assert ended.status_code in {200, 204}, ended.text
    assert (await _compiled(world, user_id)).grants == {}


def test_every_grant_change_reaches_every_process() -> None:
    """Lane B (2): the authz consumer bumps the tenant's generation on a grant's change."""
    assert SupportGrantChanged.event_type in TRIGGERS


async def test_the_licence_still_applies(world: World) -> None:  # noqa: F811 - the reused fixture
    _, user_id = await _support_user(world)
    policy = world.app.state.policy

    async def nothing_licensed(tenant_id: uuid.UUID, session: object) -> frozenset[str]:
        del tenant_id, session
        return frozenset()

    unlicensed = PolicyService(
        policy.database,
        policy.catalogue,
        memberships=policy.memberships,
        entitled_features=nothing_licensed,
    )
    subject = await _compiled(world, user_id, unlicensed)
    gated = {k for k, spec in policy.catalogue.permissions.items() if spec.feature is not None}
    assert gated, "the catalogue has licensed permissions"
    assert not (set(subject.grants) & gated)
    assert set(subject.not_entitled) & gated


async def test_sensitive_fields_are_hidden_and_personal_ones_masked(
    world: World,  # noqa: F811 - the reused fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every record type's marks reach the support subject; unmask_personal opens personal only."""

    async def fields(session: object) -> list[RuleableField]:
        del session
        return [
            RuleableField(key="custom.salary", custom=True, sensitive=True),
            RuleableField(key="custom.home_phone", custom=True, personal_data=True),
            RuleableField(key="custom.colour", custom=True),
        ]

    monkeypatch.setitem(field_access_service._CATALOGUES, "support_test", fields)  # noqa: SLF001 - a test record type
    grant_id, user_id = await _support_user(world)
    subject = await _compiled(world, user_id)
    assert dict(subject.field_access["support_test"]) == {
        "custom.home_phone": "masked",
        "custom.salary": "hidden",
    }
    await _sql(
        world,
        "UPDATE support_grants SET unmask_personal = true WHERE tenant_id = $1 AND id = $2",
        world.a.tenant,
        uuid.UUID(grant_id),
    )
    unmasked = await _compiled(world, user_id)
    assert not unmasked.mask_contacts
    assert dict(unmasked.field_access["support_test"]) == {"custom.salary": "hidden"}


async def test_support_saves_workflow_drafts_and_never_publishes_or_runs_them(
    world: World,  # noqa: F811 - the reused fixture
) -> None:
    """D-173: drafts only. A tenant admin publishes, switches on, deletes, exports and runs."""
    _, user_id = await _support_user(
        world, access="view_and_change", change_reason="Fix the stuck workflow on INC-12"
    )
    console = {"X-SupportX-Client": "console"}
    made = await world.call(
        "POST",
        "/automation/workflows",
        world.a,
        user=user_id,
        json={"record_type": "incident", "name": "Escalate"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **console},
    )
    assert made.status_code == 201, made.text
    flow = made.json()
    base = f"/automation/workflows/{flow['id']}"
    saved = await world.call(
        "PUT",
        f"{base}/draft",
        world.a,
        user=user_id,
        json={"definition": dict(workflow_admin.STARTER)},
        headers={"If-Match": '"1"', **console},
    )
    assert saved.status_code == 200, saved.text
    refused: list[tuple[str, str, dict[str, object] | None]] = [
        ("POST", f"{base}/publish", None),
        ("PUT", f"{base}/enabled", {"enabled": True}),
        ("PUT", f"{base}/start-templates", {"template_ids": []}),
        ("POST", f"{base}/jobs", {}),
        ("GET", f"{base}/export", None),
        ("POST", f"{base}/test-runs", {}),
        ("DELETE", base, None),
    ]
    for method, path, body in refused:
        found = await world.call(
            method,
            path,
            world.a,
            user=user_id,
            json=body,
            headers={"If-Match": '"2"', "Idempotency-Key": str(uuid.uuid4()), **console},
        )
        assert found.status_code == 403, (path, found.text)
        assert found.json()["code"] == "vendor_support_drafts_only", path
    # The tenant admin still publishes it.
    published = await world.call(
        "POST", f"{base}/publish", world.a, headers={"If-Match": '"2"', **console}
    )
    assert published.status_code == 200, published.text


async def test_support_uses_no_ai_feature(world: World) -> None:  # noqa: F811 - the reused fixture
    """Lane B (3): no record text reaches a model on a support account's behalf."""
    _, user_id = await _support_user(
        world, access="view_and_change", change_reason="Fix the stuck workflow on INC-12"
    )
    for method, path in (
        ("GET", "/ai/settings"),
        ("GET", f"/ai/summaries/incident/{uuid.uuid4()}"),
        ("POST", f"/ai/summaries/incident/{uuid.uuid4()}/refresh"),
    ):
        refused = await world.call(method, path, world.a, user=user_id)
        assert refused.status_code == 403, (path, refused.text)
        assert refused.json()["code"] == "vendor_support_no_ai", path
    # The tenant's own people keep it (the control).
    assert (await world.call("GET", "/ai/settings", world.a)).status_code == 200


async def test_a_view_grant_reads_but_never_writes(world: World) -> None:  # noqa: F811 - the reused fixture
    """The plan's tests: at view, reads work and a write per kind is refused (403)."""
    _, user_id = await _support_user(world)
    console = {"X-SupportX-Client": "console"}
    for path in ("/incidents", "/service-requests", "/problems", "/changes", "/releases"):
        read = await world.call("GET", path, world.a, user=user_id, headers=console)
        assert read.status_code == 200, (path, read.text)
        write = await world.call(
            "POST",
            path,
            world.a,
            user=user_id,
            json={"subject": "Mail is down"},
            headers={"Idempotency-Key": str(uuid.uuid4()), **console},
        )
        assert write.status_code == 403, (path, write.text)
    # Knowledge, CMDB and assets: their writes' permissions are not held at view (their routes
    # check a valid body first, so the decision is asserted where it is made).
    subject = await _compiled(world, user_id)
    for write_right in ("knowledge.create", "cmdb.add", "assets.manage", "sla.manage"):
        assert write_right not in subject.grants, write_right
    for read_right in ("knowledge.view", "cmdb.view", "assets.view", "sla.view"):
        assert read_right in subject.grants, read_right


async def test_a_support_account_is_never_notified_or_mailed(world: World) -> None:  # noqa: F811 - the reused fixture
    """Lane B (a): a worker renders notices unmasked, so support is never a recipient."""
    from app.modules.identity_access import mail_recipients, notifiable_people  # noqa: PLC0415

    _, user_id = await _support_user(world)
    policy = world.app.state.policy
    async with policy.database.tenant_session(TenantContext(world.a.tenant)) as session:
        assert await notifiable_people(session, [user_id, world.a.admin]) != {}
        assert user_id not in await notifiable_people(session, [user_id, world.a.admin])
        assert user_id not in await mail_recipients(session, [user_id])


async def _incident_by(world: World, user_id: uuid.UUID) -> str:  # noqa: F811 - the reused fixture
    made = await world.call(
        "POST",
        "/incidents",
        world.a,
        user=user_id,
        json={"subject": "Mail is down", "requester_id": str(world.a.admin)},
        headers={"Idempotency-Key": str(uuid.uuid4()), "X-SupportX-Client": "console"},
    )
    assert made.status_code == 201, made.text
    return str(made.json()["id"])


async def test_a_grants_activity_is_its_own_accounts_only(world: World) -> None:  # noqa: F811 - the reused fixture
    """The coordinator's Q1: never another grant's, another tenant's, or without audit.view."""
    change = {"access": "view_and_change", "change_reason": "Fix the stuck workflow on INC-12"}
    first, first_user = await _support_user(world, **change)
    second, second_user = await _support_user(
        world, engineer_email="sara@extravis.com", engineer_name="Sara Engineer", **change
    )
    mine = await _incident_by(world, first_user)
    theirs = await _incident_by(world, second_user)
    found = await world.call("GET", f"/identity/vendor-support/grants/{first}/activity", world.a)
    assert found.status_code == 200, found.text
    objects = {item["object_id"] for item in found.json()["items"]}
    assert mine in objects
    assert theirs not in objects
    assert all(set(item) == {"id", "occurred_at", "action", "outcome", "object_type",
                             "object_id"} for item in found.json()["items"])  # fmt: skip
    # Another tenant's admin finds no such grant.
    other = await world.call("GET", f"/identity/vendor-support/grants/{first}/activity", world.b)
    assert other.status_code in {403, 404}, other.text
    # The second grant's activity is its own.
    second_found = await world.call(
        "GET", f"/identity/vendor-support/grants/{second}/activity", world.a
    )
    assert {i["object_id"] for i in second_found.json()["items"]} >= {theirs}
    assert mine not in {i["object_id"] for i in second_found.json()["items"]}
