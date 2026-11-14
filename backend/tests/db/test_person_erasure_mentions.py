"""The mentions report of a person erasure, its review and redaction (D-171 a, ADR-052 S1b).

Real PostgreSQL as the application role, the incident world (org A's admin requests, the lead is
made the second admin; tech A is the person; org B for isolation).

- RLS: tenant B neither sees nor changes tenant A's mentions; the app cannot delete one.
- The build: lane B's ports (other people's profiles, file names, asset notes) find the person
  by name, e-mail and phone; the person's own profile is skipped; tenant B is never searched.
  Resumable in batches; a port registered later runs on the next pass and the review lapses.
  With S1b's REQUIRED_MENTION_PORTS the report is never complete, so approval is refused.
- Approval: `erasure_report_unavailable` (incomplete), then `erasure_report_not_reviewed`; the
  job refuses an incomplete report too.
- Passage: only through the caller's own rights; each view audited without text.
- Redaction: only the chosen field and kind, version bumped, history without text, the record's
  event, an audit entry per mention, idempotent; another erasure's mention refused (404).
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.mentions import MentionMatchKind, MentionTerms
from app.modules.identity_access.infra.models import User
from app.modules.identity_access.service import erasure_job, erasure_mentions
from app.modules.identity_access.service import person_mention_ports as lane_b
from app.modules.identity_access.service.person_data import (
    REQUIRED_MENTION_PORTS,
    Mention,
    MentionBatch,
    register_mentions,
    unregister_mentions,
)
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_asset_financials_api import _asset, _note
from tests.db.test_incidents_api import Org, World, role
from tests.db.test_person_erasure_api import _audit, _code, _request, _second_admin

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

PHONE = "+92 300 1234567"


async def _one(world: World, sql: str, *args: Any) -> Any:  # noqa: ANN401 - asyncpg values
    rows = await world.sql(sql, *args)
    return rows[0][0] if rows else None


async def _person(world: World, org: Org, user: uuid.UUID) -> dict[str, Any]:
    rows = await world.sql(
        "SELECT display_name, email, version, description, job_title, signature FROM users"
        " WHERE tenant_id = $1 AND id = $2",
        org.tenant,
        user,
    )
    return dict(rows[0])


async def _file(world: World, org: Org, name: str, owner: uuid.UUID) -> uuid.UUID:
    """A file in `owner`'s editor drafts (only they may see a draft's files)."""
    file_id = uuid.uuid4()
    await world.sql(
        "INSERT INTO files (id, tenant_id, name, size, sha256, content_type, kind, state,"
        " data_key_id, object_key, stored_size, source, created_by)"
        " VALUES ($1, $2, $3, 1, $4, 'text/plain', 'other', 'clean', $5, $6, 1, 'ui', $7)",
        file_id,
        org.tenant,
        name,
        bytes(32),
        uuid.uuid4(),
        f"{org.tenant}/{file_id}",
        owner,
    )
    await world.sql(
        "INSERT INTO file_links (id, tenant_id, file_id, owner_type, owner_id)"
        " VALUES ($1, $2, $3, 'draft', $4)",
        uuid.uuid4(),
        org.tenant,
        file_id,
        owner,
    )
    return file_id


async def _seed(world: World, org: Org) -> dict[str, Any]:
    """Tech A is named in tech B's profile, a file name and an asset note."""
    await world.sql(
        "UPDATE users SET phone = $3 WHERE tenant_id = $1 AND id = $2",
        org.tenant,
        org.tech_a,
        PHONE,
    )
    person = await _person(world, org, org.tech_a)
    name, email = person["display_name"], person["email"]
    await world.sql(
        "UPDATE users SET description = $3, job_title = $4 WHERE tenant_id = $1 AND id = $2",
        org.tenant,
        org.tech_b,
        f"Covers for {name}; call 0300-1234567 or {email}. {name.upper()} knows.",
        f"Deputy to {name}",
    )
    # The person's own profile is the erasure's to clear: never a mention.
    await world.sql(
        "UPDATE users SET signature = $3 WHERE tenant_id = $1 AND id = $2",
        org.tenant,
        org.tech_a,
        f"Regards, {name}",
    )
    file_id = await _file(world, org, f"Contract {name}.pdf", org.admin)
    other_file = await _file(world, org, "Printer manual.pdf", org.admin)
    asset = await _asset(world, org, f"Laptop {uuid.uuid4().hex[:6]}")
    note = await _note(world, org, asset, f"<p>Lent to {name} until Friday</p>")
    assert note.status_code == 201, note.text
    return {
        "name": name,
        "email": email,
        "file": file_id,
        "other_file": other_file,
        "asset": asset,
        "note": uuid.UUID(note.json()["id"]),
    }


async def _requested(world: World, org: Org) -> dict[str, Any]:
    asked = await _request(world, org, org.admin, org.tech_a)
    assert asked.status_code == 201, asked.text
    return dict(asked.json())


async def _build(world: World, org: Org) -> int:
    return await erasure_job.build_reports(world.app.state.db, org.tenant, datetime.now(UTC))


async def _get(world: World, org: Org, erasure: dict[str, Any]) -> dict[str, Any]:
    found = await world.call("GET", f"/erasures/{erasure['id']}", org, org.admin)
    assert found.status_code == 200, found.text
    return dict(found.json())


async def _mentions(world: World, org: Org, erasure: dict[str, Any]) -> dict[str, Any]:
    listed = await world.call("GET", f"/erasures/{erasure['id']}/mentions", org, org.admin)
    assert listed.status_code == 200, listed.text
    return dict(listed.json())


def _places(page: dict[str, Any]) -> set[tuple[str, str, str, str, int]]:
    return {
        (m["module_key"], m["record_type"], m["field"], m["match_kind"], m["occurrences"])
        for m in page["items"]
    }


def _find(page: dict[str, Any], module: str, field: str, kind: str) -> dict[str, Any]:
    return next(
        m
        for m in page["items"]
        if (m["module_key"], m["field"], m["match_kind"]) == (module, field, kind)
    )


# --- RLS ------------------------------------------------------------------------------------------

INSERT = text(
    "INSERT INTO person_erasure_mentions (tenant_id, id, erasure_id, module_key, record_type,"
    " record_id, field, match_kind, occurrences) VALUES (:t, :i, :e, 'files', 'file', :r,"
    " 'name', 'name', 1)"
)


async def test_tenant_b_neither_sees_nor_changes_tenant_as_mentions(world: World) -> None:
    a, b = world.a, world.b
    erasure = await _requested(world, a)
    values = {"t": a.tenant, "i": uuid.uuid4(), "e": uuid.UUID(erasure["id"]), "r": uuid.uuid4()}
    db = world.app.state.db
    async with db.tenant_session(TenantContext(a.tenant)) as session:
        await session.execute(INSERT, values)
    async with db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.execute(text("SELECT count(*) FROM person_erasure_mentions"))
        assert seen.scalar_one() == 0
        changed = await session.execute(
            text("UPDATE person_erasure_mentions SET state = 'redacted' WHERE tenant_id = :a"),
            {"a": a.tenant},
        )
        assert changed.rowcount == 0
    with pytest.raises(DBAPIError):  # B cannot write a row for A
        async with db.tenant_session(TenantContext(b.tenant)) as session:
            await session.execute(INSERT, {**values, "i": uuid.uuid4()})
    with pytest.raises(DBAPIError):  # nor point one at A's erasure under its own tenant
        async with db.tenant_session(TenantContext(b.tenant)) as session:
            await session.execute(INSERT, {**values, "t": b.tenant, "i": uuid.uuid4()})
    with pytest.raises(DBAPIError):  # the app never deletes what the approver saw
        async with db.tenant_session(TenantContext(a.tenant)) as session:
            await session.execute(text("DELETE FROM person_erasure_mentions"))
    states = await world.sql(
        "SELECT state FROM person_erasure_mentions WHERE tenant_id = $1", a.tenant
    )
    assert [row["state"] for row in states] == ["found"]


# --- the build ------------------------------------------------------------------------------------


async def test_the_report_finds_the_person_and_is_never_complete_in_s1b(world: World) -> None:
    a, b = world.a, world.b
    seeded = await _seed(world, a)
    # Tenant B names A's person too: A's report never sees it.
    await world.sql(
        "UPDATE users SET description = $3 WHERE tenant_id = $1 AND id = $2",
        b.tenant,
        b.tech_b,
        f"Ask {seeded['name']}",
    )
    erasure = await _requested(world, a)
    assert (await _get(world, a, erasure))["report"] is None
    assert await _build(world, a) >= 3  # one batch per port at least
    shown = await _get(world, a, erasure)
    report = shown["report"]
    assert report["complete"] is False
    assert report["building"] is False
    assert shown["report_ready"] is False
    assert report["attachment_content_searched"] is False
    assert report["ports_missing"] == sorted(
        REQUIRED_MENTION_PORTS - {"identity_access", "files", "assets"}
    )
    assert report["by_module"]["identity_access"] == {"name": 2, "email": 1, "phone": 1}
    assert report["by_module"]["files"] == {"name": 1}
    assert report["by_module"]["assets"] == {"name": 1}
    page = await _mentions(world, a, erasure)
    assert page["attachment_content_searched"] is False
    assert _places(page) == {
        ("identity_access", "user", "description", "name", 2),
        ("identity_access", "user", "description", "email", 1),
        ("identity_access", "user", "description", "phone", 1),
        ("identity_access", "user", "job_title", "name", 1),
        ("files", "file", "name", "name", 1),
        ("assets", "asset_note", "body", "name", 1),
    }
    ids = {m["record_id"] for m in page["items"]}
    assert str(a.tech_a) not in ids  # the person's own signature is not a mention
    assert str(b.tech_b) not in ids  # another tenant is never searched
    assert {m["state"] for m in page["items"]} == {"found"}
    # Places and counts only: the person's name, address and number appear nowhere.
    raw = json.dumps(page) + json.dumps(shown)
    for secret in (seeded["name"], seeded["email"], "1234567"):
        assert secret not in raw
    # Built once: the next run adds nothing and keeps the version.
    assert await _build(world, a) == 0
    assert (await _get(world, a, erasure))["version"] == shown["version"]
    # The person can still not be approved (S2's ports missing), even after a review.
    reviewed = await world.call(
        "POST",
        f"/erasures/{erasure['id']}/report/reviewed",
        a,
        a.admin,
        headers={"If-Match": f'"{shown["version"]}"'},
    )
    assert reviewed.status_code == 200, reviewed.text
    approver = await _second_admin(world, a)
    approved = await world.call(
        "POST",
        f"/erasures/{erasure['id']}/approve",
        a,
        approver,
        json={"confirm_name": seeded["name"]},
        headers={"If-Match": f'"{reviewed.json()["version"]}"'},
    )
    assert _code(approved) == (409, "erasure_report_unavailable")


async def test_the_build_resumes_in_batches_and_runs_a_later_port(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = world.a
    await _seed(world, a)
    for user in (a.tech_c, a.lead):  # more profiles naming the person, one batch each
        name = (await _person(world, a, a.tech_a))["display_name"]
        await world.sql(
            "UPDATE users SET description = $3 WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            user,
            f"Shadowing {name}",
        )
    monkeypatch.setattr(lane_b, "MENTION_BATCH", 1)
    erasure = await _requested(world, a)
    erasure_id = uuid.UUID(erasure["id"])
    db = world.app.state.db
    seen: list[dict[str, Any] | None] = []
    for _ in range(200):
        async with db.tenant_session(TenantContext(a.tenant)) as session:
            more = await erasure_mentions.build_report_batch(session, erasure_id)
        rows = await world.sql(
            "SELECT report FROM person_erasures WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            erasure_id,
        )
        seen.append(json.loads(rows[0]["report"]) if rows[0]["report"] else None)
        if not more:
            break
    # Progress was stored between batches: the port and its cursor.
    building = [r["building"] for r in seen if r and r.get("building")]
    assert any(b["port"] == "identity_access" and b["cursor"] for b in building)
    final = seen[-1]
    assert final is not None
    assert final["building"] is None
    assert final["by_module"]["identity_access"]["name"] == 4  # tech B twice, tech C, the lead
    # Reviewed; then a port registers (a new release): the next pass runs it, the review lapses.
    version = (await _get(world, a, erasure))["version"]
    reviewed = await world.call(
        "POST",
        f"/erasures/{erasure_id}/report/reviewed",
        a,
        a.admin,
        headers={"If-Match": f'"{version}"'},
    )
    assert reviewed.json()["report"]["reviewed_by"] == str(a.admin)

    class Later:
        module: ClassVar[str] = "knowledge"

        async def find_mentions(self, *_a: object, **_k: object) -> MentionBatch:
            return MentionBatch(
                (Mention("kb_article", uuid.uuid4(), "body", MentionMatchKind.NAME, 3),)
            )

        async def redact_mention(self, *_a: object, **_k: object) -> bool:
            return False

        async def passage(self, *_a: object, **_k: object) -> str | None:
            return None

    register_mentions(Later())  # a stand-in with the protocol's shape
    try:
        assert await _build(world, a) == 1
    finally:
        unregister_mentions("knowledge")
    shown = await _get(world, a, erasure)
    assert shown["report"]["by_module"]["knowledge"] == {"name": 1}
    assert "knowledge" not in shown["report"]["ports_missing"]
    assert shown["report"]["complete"] is False
    assert shown["report"]["reviewed_at"] is None  # the report changed: review again


# --- approval -------------------------------------------------------------------------------------


async def _complete(world: World, org: Org, erasure_id: uuid.UUID) -> None:
    """A stand-in for S2: the report marked complete (no real registry makes it so in S1b)."""
    await world.sql(
        "UPDATE person_erasures SET report = jsonb_set(report, '{complete}', 'true')"
        " WHERE tenant_id = $1 AND id = $2",
        org.tenant,
        erasure_id,
    )


async def test_approval_needs_a_complete_then_reviewed_report(world: World) -> None:
    a = world.a
    seeded = await _seed(world, a)
    approver = await _second_admin(world, a)
    erasure = await _requested(world, a)
    erasure_id = uuid.UUID(erasure["id"])

    async def approve(version: int) -> Any:  # noqa: ANN401 - httpx response
        return await world.call(
            "POST",
            f"/erasures/{erasure_id}/approve",
            a,
            approver,
            json={"confirm_name": seeded["name"]},
            headers={"If-Match": f'"{version}"'},
        )

    # Before the review: building or not, a review is refused while there is no report.
    early = await world.call(
        "POST",
        f"/erasures/{erasure_id}/report/reviewed",
        a,
        a.admin,
        headers={"If-Match": '"1"'},
    )
    assert _code(early) == (409, "erasure_report_unavailable")
    assert _code(await approve(1)) == (409, "erasure_report_unavailable")
    await _build(world, a)
    version = (await _get(world, a, erasure))["version"]
    assert _code(await approve(version)) == (409, "erasure_report_unavailable")  # incomplete
    await _complete(world, a, erasure_id)
    assert (await _get(world, a, erasure))["report_ready"] is True
    assert _code(await approve(version)) == (409, "erasure_report_not_reviewed")
    stale = await world.call(
        "POST",
        f"/erasures/{erasure_id}/report/reviewed",
        a,
        a.admin,
        headers={"If-Match": '"1"'},
    )
    assert stale.status_code == 409
    reviewed = await world.call(
        "POST",
        f"/erasures/{erasure_id}/report/reviewed",
        a,
        a.admin,
        headers={"If-Match": f'"{version}"'},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.headers["ETag"] == f'"{version + 1}"'
    logged = await _audit(world, a, "person.erasure_report_reviewed")
    assert [(e["outcome"], e["object_id"]) for e in logged if e["outcome"] == "done"] == [
        ("done", str(erasure_id))
    ]
    # Reviewed by someone else is not enough: the approver must have looked themselves.
    assert _code(await approve(version + 1)) == (409, "erasure_report_not_reviewed")
    own = await world.call(
        "POST",
        f"/erasures/{erasure_id}/report/reviewed",
        a,
        approver,
        headers={"If-Match": f'"{version + 1}"'},
    )
    assert own.status_code == 200, own.text
    approved = await approve(version + 2)
    assert approved.status_code == 200, approved.text
    states = await world.sql(
        "SELECT DISTINCT state FROM person_erasure_mentions WHERE tenant_id = $1"
        " AND erasure_id = $2",
        a.tenant,
        erasure_id,
    )
    assert [row["state"] for row in states] == ["left"]  # the approver left them in place


async def test_the_job_refuses_an_incomplete_report(world: World) -> None:
    a = world.a
    approver = await _second_admin(world, a)
    erasure = await _requested(world, a)
    erasure_id = uuid.UUID(erasure["id"])
    await _build(world, a)
    await world.sql(
        "UPDATE person_erasures SET state = 'approved', approved_by = $3, approved_at = now(),"
        " report_reviewed_at = now() WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        erasure_id,
        approver,
    )
    outcome = await erasure_job.run_erasure(
        world.app.state.db, a.tenant, erasure_id, erasure_job.JobEffects()
    )
    assert (outcome.state, outcome.error_code) == ("failed", "erasure_report_unavailable")
    status = await _one(
        world, "SELECT status FROM users WHERE tenant_id = $1 AND id = $2", a.tenant, a.tech_a
    )
    assert status == "active"


# --- passage --------------------------------------------------------------------------------------


async def test_a_passage_needs_the_callers_own_rights_and_is_audited(world: World) -> None:
    a, b = world.a, world.b
    seeded = await _seed(world, a)
    erasure = await _requested(world, a)
    await _build(world, a)
    page = await _mentions(world, a, erasure)
    profile = _find(page, "identity_access", "description", "name")
    file_name = _find(page, "files", "name", "name")
    note = _find(page, "assets", "body", "name")
    base = f"/erasures/{erasure['id']}/mentions"

    shown = await world.call("GET", f"{base}/{profile['id']}/passage", a, a.admin)
    assert shown.status_code == 200, shown.text
    assert seeded["name"] in shown.json()["text"]
    assert shown.headers["Cache-Control"] == "no-store"
    named = await world.call("GET", f"{base}/{file_name['id']}/passage", a, a.admin)
    assert named.json()["text"] == f"Contract {seeded['name']}.pdf"
    noted = await world.call("GET", f"{base}/{note['id']}/passage", a, a.admin)
    assert seeded["name"] in noted.json()["text"]

    # An eraser without the record rights: tech C may erase, but neither read people's
    # descriptions nor see the admin's draft files nor any asset.
    eraser = await role(world, a, "Privacy clerk", [("people.erase", "all")])
    assigned = await world.call("PUT", f"/users/{a.tech_c}/roles/{eraser}", a, a.admin)
    assert assigned.status_code == 204, assigned.text
    for mention in (profile, file_name):
        hidden = await world.call("GET", f"{base}/{mention['id']}/passage", a, a.tech_c)
        assert _code(hidden) == (404, "erasure_mention_not_found")
    # Not for another tenant, nor through another erasure's ID.
    elsewhere = await world.call("GET", f"{base}/{profile['id']}/passage", b, b.admin)
    assert _code(elsewhere) == (404, "erasure_not_found")
    viewed = await _audit(world, a, "person.erasure_mention_viewed")
    assert [e["details"]["mention_id"] for e in viewed] == [
        profile["id"],
        file_name["id"],
        note["id"],
    ]
    assert seeded["name"] not in json.dumps(viewed)  # IDs only, never the text


# --- redaction ------------------------------------------------------------------------------------


async def _redact(world: World, org: Org, erasure_id: str, ids: list[str], version: int) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "POST",
        f"/erasures/{erasure_id}/mentions/redact",
        org,
        org.admin,
        json={"mention_ids": ids},
        headers={"If-Match": f'"{version}"'},
    )


async def test_redaction_changes_only_the_chosen_field_and_kind(
    world: World,
) -> None:
    a = world.a
    seeded = await _seed(world, a)
    name, email = seeded["name"], seeded["email"]
    erasure = await _requested(world, a)
    await _build(world, a)
    page = await _mentions(world, a, erasure)
    profile = _find(page, "identity_access", "description", "name")
    file_name = _find(page, "files", "name", "name")
    note = _find(page, "assets", "body", "name")
    before = await _person(world, a, a.tech_b)
    version = (await _get(world, a, erasure))["version"]

    done = await _redact(
        world, a, erasure["id"], [profile["id"], file_name["id"], note["id"]], version
    )
    assert done.status_code == 200, done.text
    assert done.headers["ETag"] == f'"{version + 1}"'
    assert {m["id"] for m in done.json()["redacted"]} == {
        profile["id"],
        file_name["id"],
        note["id"],
    }
    assert {m["state"] for m in done.json()["redacted"]} == {"redacted"}

    # The profile: only the description's name occurrences; e-mail, phone and job title stay.
    after = await _person(world, a, a.tech_b)
    assert after["version"] == before["version"] + 1
    assert name.casefold() not in after["description"].casefold()
    assert after["description"].count("erased_on_request") == 2
    assert email in after["description"]
    assert "0300-1234567" in after["description"]
    assert after["job_title"] == before["job_title"]
    history = await world.sql(
        "SELECT field, old_value #>> '{}' AS old_value, new_value #>> '{}' AS new_value,"
        " reason FROM field_changes WHERE tenant_id = $1"
        " AND record_type = 'user' AND record_id = $2 AND record_version = $3",
        a.tenant,
        a.tech_b,
        after["version"],
    )
    assert [(h["field"], h["old_value"], h["new_value"], h["reason"]) for h in history] == [
        ("description", None, None, "erasure_redaction")
    ]
    updated = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'identity_access.user.updated' AND aggregate_id = $2",
        a.tenant,
        str(a.tech_b),
    )
    assert any(
        json.loads(e["envelope"])["payload"]["changed_fields"] == ["description"] for e in updated
    )
    # The file: renamed, versioned, its screens told.
    file_row = (
        await world.sql(
            "SELECT name, version FROM files WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            seeded["file"],
        )
    )[0]
    assert (file_row["name"], file_row["version"]) == ("Contract erased_on_request.pdf", 2)
    file_history = await world.sql(
        "SELECT field, old_value #>> '{}' AS old_value, new_value #>> '{}' AS new_value,"
        " reason FROM field_changes WHERE tenant_id = $1"
        " AND record_type = 'file' AND record_id = $2",
        a.tenant,
        seeded["file"],
    )
    assert [(h["field"], h["old_value"], h["new_value"], h["reason"]) for h in file_history] == [
        ("name", None, None, "erasure_redaction")
    ]
    assert (
        await _one(
            world,
            "SELECT name FROM files WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            seeded["other_file"],
        )
        == "Printer manual.pdf"
    )
    # The note: redacted, versioned, its history without text.
    body = await _one(
        world,
        "SELECT body FROM asset_notes WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        seeded["note"],
    )
    assert "erased_on_request" in body
    assert name not in body
    note_history = await world.sql(
        "SELECT old_value #>> '{}' AS old_value, new_value #>> '{}' AS new_value, reason"
        " FROM field_changes WHERE tenant_id = $1"
        " AND record_type = 'asset_note' AND record_id = $2 AND field = 'body'"
        " ORDER BY occurred_at DESC LIMIT 1",
        a.tenant,
        seeded["note"],
    )
    assert dict(note_history[0]) == {
        "old_value": None,
        "new_value": None,
        "reason": "erasure_redaction",
    }
    note_events = await world.sql(
        "SELECT count(*) FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'assets.note.changed' AND aggregate_id = $2",
        a.tenant,
        str(seeded["note"]),
    )
    assert note_events[0][0] == 2  # added, then redacted
    # One audit entry per mention, IDs only.
    logged = await _audit(world, a, "person.erasure_mention_redacted")
    assert sorted(e["details"]["mention_id"] for e in logged) == sorted(
        [profile["id"], file_name["id"], note["id"]]
    )
    assert name not in json.dumps(logged)
    # Idempotent: again, nothing changes, nothing is audited.
    again = await _redact(world, a, erasure["id"], [profile["id"]], version + 1)
    assert again.status_code == 200, again.text
    assert again.json()["redacted"] == []
    assert (await _person(world, a, a.tech_b))["version"] == after["version"]
    assert len(await _audit(world, a, "person.erasure_mention_redacted")) == 3
    # The other kinds are still found, and can be redacted on their own.
    rest = await _mentions(world, a, erasure)
    still = {(m["field"], m["match_kind"]) for m in rest["items"] if m["state"] == "found"}
    assert still == {("description", "email"), ("description", "phone"), ("job_title", "name")}


async def test_another_erasures_mention_or_a_closed_erasure_is_refused(world: World) -> None:
    a, b = world.a, world.b
    await _seed(world, a)
    await _seed(world, b)
    mine = await _requested(world, a)
    other = await _requested(world, b)
    await _build(world, a)
    await _build(world, b)
    theirs = (await _mentions(world, b, other))["items"][0]
    version = (await _get(world, a, mine))["version"]
    refused = await _redact(world, a, mine["id"], [theirs["id"]], version)
    assert _code(refused) == (404, "erasure_mention_not_found")
    ours = (await _mentions(world, a, mine))["items"][0]
    mixed = await _redact(world, a, mine["id"], [ours["id"], str(uuid.uuid4())], version)
    assert _code(mixed) == (404, "erasure_mention_not_found")
    assert {m["state"] for m in (await _mentions(world, a, mine))["items"]} == {"found"}
    assert (await _get(world, a, mine))["version"] == version  # nothing moved
    rejected = await world.call(
        "POST",
        f"/erasures/{mine['id']}/reject",
        a,
        a.admin,
        json={},
        headers={"If-Match": f'"{version}"'},
    )
    assert rejected.status_code == 200, rejected.text
    closed = await _redact(world, a, mine["id"], [ours["id"]], version + 1)
    assert _code(closed) == (409, "erasure_not_pending")
    too_many = await _redact(world, a, mine["id"], [str(uuid.uuid4())] * 201, version + 1)
    assert too_many.status_code == 422


# --- lane B's ports, on their own -----------------------------------------------------------------


async def test_lane_b_ports_find_redact_and_stay_in_their_tenant(world: World) -> None:
    a, b = world.a, world.b
    seeded = await _seed(world, a)
    await _seed(world, b)
    db = world.app.state.db
    port = lane_b.IdentityAccessMentions()
    async with db.tenant_session(TenantContext(a.tenant)) as session:
        person = await session.get(User, a.tech_a)
        assert person is not None
        terms = erasure_mentions.person_terms(person)
        batch = await port.find_mentions(session, a.tech_a, terms=terms, cursor=None)
    assert {m.record_id for m in batch.mentions} == {a.tech_b}
    title = next(m for m in batch.mentions if m.field == "job_title")
    b_before = await _person(world, b, b.tech_b)
    for round_ in (1, 2):
        async with db.tenant_session(TenantContext(a.tenant)) as session:
            changed = await port.redact_mention(
                session, title, terms=terms, marker="erased_on_request", now=datetime.now(UTC)
            )
        assert changed is (round_ == 1)  # idempotent: nothing left to replace
    assert (await _person(world, a, a.tech_b))["job_title"] == "Deputy to erased_on_request"
    assert await _person(world, b, b.tech_b) == b_before  # another tenant untouched
    # A mention pointed at another tenant's row finds nothing to change (RLS).
    elsewhere = Mention("user", b.tech_b, "description", MentionMatchKind.NAME, 1)
    async with db.tenant_session(TenantContext(a.tenant)) as session:
        assert not await port.redact_mention(
            session, elsewhere, terms=terms, marker="erased_on_request", now=datetime.now(UTC)
        )
    async with db.tenant_session(TenantContext(a.tenant)) as session:
        files = await lane_b.FilesMentions().find_mentions(
            session, a.tech_a, terms=terms, cursor=None
        )
        none = await lane_b.FilesMentions().find_mentions(
            session, a.tech_a, terms=MentionTerms(), cursor=None
        )
    assert [m.record_id for m in files.mentions] == [seeded["file"]]
    assert none.mentions == ()


async def test_nobody_redacts_a_mention_they_cannot_read(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lane B's review of S1b: redaction needs the same read rights as viewing the passage."""
    a = world.a
    await _seed(world, a)
    erasure = await _requested(world, a)
    await _build(world, a)
    profile = _find(await _mentions(world, a, erasure), "identity_access", "description", "name")
    before = await _person(world, a, a.tech_b)

    async def unreadable(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(lane_b.IdentityAccessMentions, "passage", unreadable)
    version = (await _get(world, a, erasure))["version"]
    refused = await _redact(world, a, erasure["id"], [profile["id"]], version)
    assert _code(refused) == (404, "erasure_mention_not_found")
    assert await _person(world, a, a.tech_b) == before  # nothing changed
    assert (await _get(world, a, erasure))["version"] == version


async def _history_row(
    world: World, org: Org, record_id: uuid.UUID, field: str, value: str, change_id: uuid.UUID
) -> uuid.UUID:
    row_id = uuid.uuid4()
    await world.sql(
        "INSERT INTO field_changes (id, tenant_id, record_type, record_id, record_version,"
        " change_id, kind, field, old_value, new_value, actor_type, source, occurred_at)"
        " VALUES ($1, $2, 'user', $3, 1, $4, 'updated', $5, to_jsonb($6::text),"
        " to_jsonb($6::text), 'user', 'ui', now())",
        row_id,
        org.tenant,
        record_id,
        change_id,
        field,
        value,
    )
    return row_id


async def _values(world: World, org: Org, row_id: uuid.UUID) -> tuple[Any, Any]:
    rows = await world.sql(
        "SELECT old_value, new_value FROM field_changes WHERE tenant_id = $1 AND id = $2",
        org.tenant,
        row_id,
    )
    return rows[0]["old_value"], rows[0]["new_value"]


async def test_redaction_blanks_only_the_mentions_field_in_history(world: World) -> None:
    """history_redact_field: the mention row's record and field only; fingerprinted rows kept."""
    a, b = world.a, world.b
    seeded = await _seed(world, a)
    name = seeded["name"]
    earlier = await _history_row(
        world, a, a.tech_b, "description", f"Covers for {name}", uuid.uuid4()
    )
    other_field = await _history_row(
        world, a, a.tech_b, "job_title", f"Deputy to {name}", uuid.uuid4()
    )
    # A row a fingerprinted audit entry commits to (ADR-046): blanking it would read as tampering.
    signed_change = await _one(
        world,
        "SELECT fingerprint_saves[1] FROM audit_entries WHERE tenant_id = $1"
        " AND fingerprint_saves IS NOT NULL ORDER BY occurred_at LIMIT 1",
        a.tenant,
    )
    assert signed_change is not None
    signed = await _history_row(world, a, a.tech_b, "description", f"Signed {name}", signed_change)
    # The same record and field in tenant B is never touched.
    elsewhere = await _history_row(
        world, b, a.tech_b, "description", f"Covers for {name}", uuid.uuid4()
    )
    erasure = await _requested(world, a)
    await _build(world, a)
    page = await _mentions(world, a, erasure)
    profile = _find(page, "identity_access", "description", "name")
    assert profile["history_kept"] == 0
    version = (await _get(world, a, erasure))["version"]

    done = await _redact(world, a, erasure["id"], [profile["id"]], version)
    assert done.status_code == 200, done.text
    assert [m["history_kept"] for m in done.json()["redacted"]] == [1]
    assert await _values(world, a, earlier) == (None, None)
    assert await _values(world, a, other_field) != (None, None)
    assert await _values(world, a, signed) != (None, None)
    assert await _values(world, b, elsewhere) != (None, None)
    assert (
        await _one(
            world,
            "SELECT history_kept FROM person_erasure_mentions WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            uuid.UUID(profile["id"]),
        )
        == 1
    )


async def test_history_redaction_needs_a_redacted_mention(world: World) -> None:
    """The function takes a mention ID only, and acts only once that mention is redacted."""
    a = world.a
    seeded = await _seed(world, a)
    earlier = await _history_row(
        world, a, a.tech_b, "description", f"Covers for {seeded['name']}", uuid.uuid4()
    )
    erasure = await _requested(world, a)
    await _build(world, a)
    profile = _find(await _mentions(world, a, erasure), "identity_access", "description", "name")
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        found = await session.scalar(
            text("SELECT history_redact_field(:m)"), {"m": uuid.UUID(profile["id"])}
        )
        unknown = await session.scalar(text("SELECT history_redact_field(:m)"), {"m": uuid.uuid4()})
    assert found == {"blanked": 0, "kept_fingerprinted": 0}
    assert unknown == {"blanked": 0, "kept_fingerprinted": 0}
    assert await _values(world, a, earlier) != (None, None)


async def test_profile_history_is_erased_only_once_the_person_is_erased(world: World) -> None:
    """audit_erase_profile_history: guarded by users.erased_at; other people untouched."""
    a = world.a
    own = await _history_row(world, a, a.tech_a, "description", "My own words", uuid.uuid4())
    other = await _history_row(world, a, a.tech_b, "description", "Theirs", uuid.uuid4())
    call = text("SELECT audit_erase_profile_history(:p)")
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await session.scalar(call, {"p": a.tech_a}) == 0
    assert await _values(world, a, own) != (None, None)
    await world.sql(
        "UPDATE users SET erased_at = now() WHERE tenant_id = $1 AND id = $2", a.tenant, a.tech_a
    )
    try:
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            assert await session.scalar(call, {"p": a.tech_a}) >= 1
            assert await session.scalar(call, {"p": a.tech_a}) == 0  # idempotent
        assert await _values(world, a, own) == (None, None)
        assert await _values(world, a, other) != (None, None)
        # Tenant B's session cannot reach tenant A's history, even for an erased person.
        late = await _history_row(world, a, a.tech_a, "job_title", "Later words", uuid.uuid4())
        async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
            assert await session.scalar(call, {"p": a.tech_a}) == 0
        assert await _values(world, a, late) != (None, None)
    finally:  # the shared world's person stays usable for the other tests
        await world.sql(
            "UPDATE users SET erased_at = NULL WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            a.tech_a,
        )
