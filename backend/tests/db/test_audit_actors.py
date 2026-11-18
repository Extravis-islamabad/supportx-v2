"""The audit names the real actor (WP-057 S4b, REQ-AUD-014).

A person's API key writes the key as the actor and the person as `on_behalf`; the person, never
the key, is whose personal data (the IP, the device) the entry holds, so erasing them still finds
it. The audit API names both.
"""

import json
import uuid
from typing import Any

import asyncpg
import pytest

from app.core.tenancy import AgentActor, TenantContext
from app.modules.audit import RequestFacts, record
from app.modules.audit.domain.catalogue import AuditClient
from app.modules.audit.service.exports import _matches
from app.modules.identity_access import create_service_identity
from tests.db.test_api_keys import _as_key, _make, _signed_in
from tests.db.test_auth_bff import Bff, bff  # noqa: F401 - the fixture, reused

pytestmark = pytest.mark.db
FACTS = RequestFacts(AuditClient.API, "req-s4b", "10.20.30.40", "s4b-test")


async def test_a_persons_key_is_the_actor_on_their_behalf(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)
    me = (await bff.me()).json()["user"]["id"]
    made = (await _make(bff, csrf, scopes=["incidents:read", "incidents:write"])).json()
    async with _as_key(bff, made["key"]) as api:
        created = await api.post(
            "/api/v1/incidents",
            json={"subject": "Made with a key", "requester_id": me},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
    assert created.status_code == 201, created.text
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        entries = await conn.fetch(
            "SELECT id, actor_type, actor_id, on_behalf_id FROM audit_entries WHERE object_id = $1",
            created.json()["id"],
        )
        assert entries, "the save wrote no entry"
        assert {(e["actor_type"], str(e["actor_id"]), str(e["on_behalf_id"])) for e in entries} == {
            ("api_key", made["id"], me)
        }
        subjects = await conn.fetch(
            "SELECT DISTINCT subject_id FROM audit_personal WHERE entry_id = ANY($1::uuid[])",
            [e["id"] for e in entries],
        )
        assert {str(s["subject_id"]) for s in subjects} <= {me}
    finally:
        await conn.close()
    shown = await bff.client.get(f"/api/v1/audit/entries/{entries[0]['id']}")
    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert (body["actor_type"], body["actor_name"], body["on_behalf_id"]) == (
        "api_key",
        "Nightly export",
        me,
    )


async def _tenant_and_me(world: Bff) -> tuple[uuid.UUID, uuid.UUID]:
    me = uuid.UUID((await world.me()).json()["user"]["id"])
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        tenant = await conn.fetchval("SELECT tenant_id FROM users WHERE id = $1", me)
    finally:
        await conn.close()
    return tenant, me


async def _entry(world: Bff, entry_id: uuid.UUID) -> tuple[asyncpg.Record, set[uuid.UUID]]:
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        row = await conn.fetchrow(
            "SELECT actor_type, actor_id, on_behalf_id, details FROM audit_entries WHERE id = $1",
            entry_id,
        )
        subjects = await conn.fetch(
            "SELECT subject_id FROM audit_personal WHERE entry_id = $1", entry_id
        )
    finally:
        await conn.close()
    assert row is not None
    return row, {s["subject_id"] for s in subjects}


async def test_a_service_accounts_key_is_the_account_in_a_real_session(bff: Bff) -> None:  # noqa: F811
    """Lane B (#531): through record() in a real session, the account is the actor."""
    await _signed_in(bff)
    tenant, _ = await _tenant_and_me(bff)
    key_id = uuid.uuid4()
    async with bff.app.state.db.tenant_session(TenantContext(tenant)) as session:
        account = await create_service_identity(session, name="Nightly sync")
    context = TenantContext(
        tenant, account, api_key_id=key_id, api_scopes=frozenset(), service_identity=True
    )
    async with bff.app.state.db.tenant_session(context) as session:
        entry_id = await record(session, action_code="api_key.refused", facts=FACTS)
    row, subjects = await _entry(bff, entry_id)
    assert (row["actor_type"], row["actor_id"], row["on_behalf_id"]) == (
        "service_account",
        account,
        None,
    )
    assert _details(row)["api_key_id"] == str(key_id)
    assert subjects == {account}


async def test_a_fake_agent_acts_for_the_person_in_a_real_session(bff: Bff) -> None:  # noqa: F811
    """Lane B (#531): the agent is the actor, the person on_behalf and the personal subject."""
    await _signed_in(bff)
    tenant, me = await _tenant_and_me(bff)
    agent = AgentActor(uuid.uuid4(), "triage_helper", "3", ("search_kb",))
    async with bff.app.state.db.tenant_session(TenantContext(tenant, me, agent=agent)) as session:
        entry_id = await record(session, action_code="api_key.refused", facts=FACTS)
    row, subjects = await _entry(bff, entry_id)
    assert (row["actor_type"], row["actor_id"], row["on_behalf_id"]) == ("ai_agent", agent.id, me)
    assert _details(row)["agent"] == {
        "key": "triage_helper",
        "version": "3",
        "tools": ["search_kb"],
    }
    assert subjects == {me}  # the IP is the person's, never the agent's


async def test_a_persons_filter_and_export_include_their_keys_actions(bff: Bff) -> None:  # noqa: F811
    """Lane B (#531): filtering by a person finds what their key did for them."""
    csrf = await _signed_in(bff)
    me = (await bff.me()).json()["user"]["id"]
    made = (await _make(bff, csrf, scopes=["incidents:read", "incidents:write"])).json()
    async with _as_key(bff, made["key"]) as api:
        created = await api.post(
            "/api/v1/incidents",
            json={"subject": "Made with a key", "requester_id": me},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
    assert created.status_code == 201, created.text
    either = {
        "or": [
            {"field": "actor_id", "op": "eq", "value": me},
            {"field": "on_behalf_id", "op": "eq", "value": me},
        ]
    }
    listed = await bff.client.get("/api/v1/audit/entries", params={"filter": json.dumps(either)})
    assert listed.status_code == 200, listed.text
    found = {e["object_id"] for e in listed.json()["items"] if e["actor_type"] == "api_key"}
    assert created.json()["id"] in found
    assert _matches({"actor_id": made["id"], "on_behalf_id": me}, "actor_id", me)
    assert not _matches({"actor_id": made["id"], "on_behalf_id": None}, "actor_id", me)


def _details(row: asyncpg.Record) -> dict[str, Any]:
    raw = row["details"]
    return dict(json.loads(raw) if isinstance(raw, str) else raw)
