"""The person erasure job (ADR-052 §3), driven directly: approval is refused in S1, so these tests
put an approved erasure (with a stand-in mentions report) in the table themselves. That bypass
lives here only; the API test proves no approval or run happens without the report.

- The happy path: steps 0-7 in order; frozen (disabled, no sign-in, sessions ended, Keycloak
  sessions queued to end, API keys revoked); mail forgotten; Keycloak membership removed and the
  account deleted only when no other tenant has it; every port in registry order, one batch per
  transaction; the person row anonymised with the D6b code; audit.erase_subject; the events.
- Run twice: nothing changes. A failing step rolls back, records a code, and resumes there.
- A missing required port, a hold at job start: refused for good, audited.
- Another tenant is untouched.
"""

import json
import os
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar, cast

import pytest

from app.core.tenancy import TenantContext
from app.modules.identity_access.domain import erasure as rules
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdmin,
    IdentityAdminUnavailable,
    Organization,
)
from app.modules.identity_access.service import erasure_job, person_data
from app.modules.identity_access.service.person_data import (
    ErasureBatch,
    PersonData,
    register_person_data,
    registered_ports,
    unregister_person_data,
)
from conftest import assign_system_role
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import Org, World

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the incidents fixture, re-used


class FakeKeycloak:
    """The admin API calls the job makes; `others` = the tenants the account still has."""

    def __init__(self, others: list[str] | None = None, *, down: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.others = others or []
        self.down = down

    async def organization(self, slug: str, tenant_id: str) -> Organization:
        if self.down:
            raise IdentityAdminUnavailable
        return Organization(f"org-{tenant_id}", slug, slug, (), {})

    async def remove_member(self, organization_id: str, user_id: str) -> None:
        del organization_id
        self.calls.append(("remove_member", user_id))

    async def member_tenants(self, user_id: str) -> list[str]:
        self.calls.append(("member_tenants", user_id))
        return list(self.others)

    async def delete_user(self, user_id: str) -> None:
        self.calls.append(("delete_user", user_id))


class Effects:
    """Fakes for everything outside the database, recording what the job asked."""

    def __init__(self, keycloak: FakeKeycloak | None = None) -> None:
        self.keycloak = keycloak or FakeKeycloak()
        self.mail: list[str] = []
        self.ended: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def forget_mail(self, session: object, address: str) -> int:
        del session
        self.mail.append(address)
        return 3

    async def end(self, tenant: uuid.UUID, user: uuid.UUID) -> None:
        self.ended.append((tenant, user))

    async def keycloak_sessions(self, tenant: uuid.UUID, user: uuid.UUID) -> list[str]:
        del tenant, user
        return ["kc-session-1"]

    def job(self) -> erasure_job.JobEffects:
        return erasure_job.JobEffects(
            identity_admin=cast("IdentityAdmin", self.keycloak),
            end_sessions=self.end,
            keycloak_sessions=self.keycloak_sessions,
            forget_mail=self.forget_mail,
        )


async def _one(world: World, sql: str, *args: Any) -> Any:  # noqa: ANN401 - asyncpg values
    rows = await world.sql(sql, *args)
    return rows[0][0] if rows else None


async def _seed(world: World, org: Org) -> dict[str, uuid.UUID]:
    """tech_a's data across lane B's tables; tech_b gets the same, to prove they are untouched."""
    ids: dict[str, uuid.UUID] = {}
    for person in (org.tech_a, org.tech_b):
        await world.sql(
            "INSERT INTO api_keys (id, tenant_id, owner_id, name, scopes, secret_hash, last_four,"
            " ip_allowlist, last_used_ip) VALUES ($1, $2, $3, 'laptop', '{incidents:read}',"
            " $4, 'abcd', '{10.0.0.1}', '10.0.0.9')",
            uuid.uuid4(),
            org.tenant,
            person,
            os.urandom(32),
        )
        await world.sql(
            "INSERT INTO user_cost_rates (id, tenant_id, user_id, rate, currency, effective_from)"
            " VALUES ($1, $2, $3, 40, 'USD', now())",
            uuid.uuid4(),
            org.tenant,
            person,
        )
        await world.sql(
            "INSERT INTO list_settings (id, tenant_id, user_id, list_key, view_key)"
            " VALUES ($1, $2, $3, 'assets', 'all')",
            uuid.uuid4(),
            org.tenant,
            person,
        )
        await world.sql(
            "INSERT INTO audit_saved_searches (id, tenant_id, owner_id, name, query)"
            " VALUES ($1, $2, $3, 'mine', '{}')",
            uuid.uuid4(),
            org.tenant,
            person,
        )
    for name, owner in (("gone", org.tech_a), ("kept", org.tech_a), ("other", org.tech_b)):
        file_id = uuid.uuid4()
        await world.sql(
            "INSERT INTO files (id, tenant_id, name, size, sha256, content_type, kind, state,"
            " data_key_id, object_key, stored_size, source, created_by)"
            " VALUES ($1, $2, 'a.txt', 1, $3, 'text/plain', 'other', 'clean', $4, $5, 1, 'ui', $6)",
            file_id,
            org.tenant,
            bytes(32),
            uuid.uuid4(),
            f"{org.tenant}/{file_id}",
            owner,
        )
        ids[name] = file_id
    # tech_a leads group GA (they are a member of S1 and GA, see make_org).
    await world.sql(
        "UPDATE support_groups SET lead_id = $3 WHERE tenant_id = $1 AND id = $2",
        org.tenant,
        org.ga,
        org.tech_a,
    )
    await world.sql(
        "UPDATE users SET phone = '+92 300 1234567', job_title = 'Engineer', signature = 'Ali'"
        " WHERE tenant_id = $1 AND id = $2",
        org.tenant,
        org.tech_a,
    )
    return ids


async def _approved(
    world: World,
    org: Org,
    person: uuid.UUID,
    *,
    keep: Mapping[str, str] | None = None,
    report: bool = True,
) -> uuid.UUID:
    """An approved erasure, written directly (S1 refuses approval; this is the tests' bypass)."""
    await assign_system_role(world.db.admin_url, org.tenant, org.lead, "tenant_admin")
    erasure_id = uuid.uuid4()
    await world.sql(
        "INSERT INTO person_erasures (id, tenant_id, person_id, state, reason_code, successor_id,"
        " keep_files, requested_by, requested_at, expires_at, approved_by, approved_at, report)"
        " VALUES ($1, $2, $3, 'approved', 'subject_request', $4, $5, $6, now(),"
        " now() + interval '7 days', $7, now(), $8)",
        erasure_id,
        org.tenant,
        person,
        org.tech_c,
        json.dumps(dict(keep or {})),
        org.admin,
        org.lead,
        json.dumps({"mentions": []}) if report else None,
    )
    return erasure_id


async def _run(world: World, org: Org, erasure_id: uuid.UUID, effects: Effects) -> Any:  # noqa: ANN401 - RunOutcome
    return await erasure_job.run_erasure(world.app.state.db, org.tenant, erasure_id, effects.job())


async def _row(world: World, org: Org, erasure_id: uuid.UUID) -> dict[str, Any]:
    rows = await world.sql(
        "SELECT * FROM person_erasures WHERE tenant_id = $1 AND id = $2", org.tenant, erasure_id
    )
    return dict(rows[0])


async def _counts(world: World, org: Org, person: uuid.UUID) -> dict[str, int]:
    tables = {
        "live_keys": "SELECT count(*) FROM api_keys WHERE tenant_id = $1 AND owner_id = $2"
        " AND revoked_at IS NULL",
        "rates": "SELECT count(*) FROM user_cost_rates WHERE tenant_id = $1 AND user_id = $2",
        "lists": "SELECT count(*) FROM list_settings WHERE tenant_id = $1 AND user_id = $2",
        "searches": "SELECT count(*) FROM audit_saved_searches WHERE tenant_id = $1"
        " AND owner_id = $2",
        "live_files": "SELECT count(*) FROM files WHERE tenant_id = $1 AND created_by = $2"
        " AND deleted_at IS NULL",
        "roles": "SELECT count(*) FROM user_roles WHERE tenant_id = $1 AND user_id = $2",
        "groups": "SELECT count(*) FROM group_members WHERE tenant_id = $1 AND user_id = $2",
        "sites": "SELECT count(*) FROM site_members WHERE tenant_id = $1 AND user_id = $2",
    }
    return {name: int(await _one(world, sql, org.tenant, person)) for name, sql in tables.items()}


async def _events(world: World, org: Org, event_type: str) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type = $2"
        " ORDER BY created_at",
        org.tenant,
        event_type,
    )
    return [json.loads(row["envelope"])["payload"] for row in rows]


async def _audits(world: World, org: Org, action: str) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT outcome, reason_code, object_id, details FROM audit_entries"
        " WHERE tenant_id = $1 AND action = $2 ORDER BY occurred_at",
        org.tenant,
        action,
    )
    return [{**dict(row), "details": json.loads(row["details"])} for row in rows]


class Spy:
    """Wraps the registered ports and records the order the job calls them in."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []
        real = registered_ports()
        spy = self

        class Wrapped:
            def __init__(self, port: PersonData) -> None:
                self.port = port
                self.module = port.module
                self.order = port.order

            async def erase_person(self, *args: Any, **kwargs: Any) -> ErasureBatch:  # noqa: ANN401 - passed on
                spy.calls.append(self.module)
                return await self.port.erase_person(*args, **kwargs)

        wrapped = [Wrapped(port) for port in real]
        monkeypatch.setattr(erasure_job, "registered_ports", lambda: wrapped)


async def test_the_whole_erasure_in_order(  # noqa: PLR0915 - one run, every promise checked
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = world.a, world.b
    files = await _seed(world, a)
    await _seed(world, b)
    before_b = await _counts(world, b, b.tech_a)
    email = await _one(world, "SELECT email FROM users WHERE id = $1", a.tech_a)
    spy = Spy(monkeypatch)
    effects = Effects()
    erasure_id = await _approved(world, a, a.tech_a, keep={str(files["kept"]): "Signed contract"})

    outcome = await _run(world, a, erasure_id, effects)

    assert (outcome.state, outcome.step, outcome.error_code) == ("done", 8, None)
    row = await _row(world, a, erasure_id)
    assert row["effective_successor_id"] == a.tech_c
    assert (row["port_module"], row["port_cursor"], row["last_error_code"]) == (None, None, None)
    # Ports ran once each, in registry order (references before owned rows, files last).
    assert spy.calls == [p.module for p in registered_ports()]
    assert spy.calls.index("organization") < spy.calls.index("identity_access")
    assert spy.calls[-1] == "files"
    # Frozen, sessions ended, Keycloak sessions queued through ADR-051's path.
    assert effects.ended == [(a.tenant, a.tech_a)]
    pending = await _events(world, a, "identity_access.keycloak_session.end_pending")
    assert pending == [{"user_id": str(a.tech_a), "keycloak_session_id": "kc-session-1"}]
    # Mail forgotten while the address still existed.
    assert effects.mail == [email]
    # Keycloak: membership removed; no other tenant, so the account went.
    account = f"sub-{a.tech_a}"
    assert effects.keycloak.calls == [
        ("remove_member", account),
        ("member_tenants", account),
        ("delete_user", account),
    ]
    # Lane B's data gone; the kept file stays; group lead passed to the successor.
    assert await _counts(world, a, a.tech_a) == {
        "live_keys": 0,
        "rates": 0,
        "lists": 0,
        "searches": 0,
        "live_files": 1,
        "roles": 0,
        "groups": 0,
        "sites": 0,
    }
    kept = await _one(world, "SELECT deleted_at FROM files WHERE id = $1", files["kept"])
    assert kept is None
    lead = await _one(
        world, "SELECT lead_id FROM support_groups WHERE tenant_id = $1 AND id = $2", a.tenant, a.ga
    )
    assert lead == a.tech_c
    (file_kept,) = await _audits(world, a, "person.erasure_file_kept")
    assert file_kept["object_id"] == str(files["kept"])
    # The person row: anonymised with the D6b code, nothing personal left.
    person = dict(
        (
            await world.sql(
                "SELECT display_name, first_name, last_name, email, external_subject, phone,"
                " job_title, signature, status, can_sign_in, erased_at, erased_by FROM users"
                " WHERE id = $1",
                a.tech_a,
            )
        )[0]
    )
    code = rules.erased_code(a.tech_a)
    assert person["display_name"] == f"Erased person {code}"
    assert (person["first_name"], person["last_name"]) == ("Erased person", code)
    assert person["email"] == f"erased-{a.tech_a}@invalid"
    assert (person["external_subject"], person["phone"], person["job_title"]) == (None, None, None)
    assert person["signature"] is None
    assert (person["status"], person["can_sign_in"]) == ("disabled", False)
    assert person["erased_at"] is not None
    assert person["erased_by"] == a.lead
    # Audit: the subject erased; the erasure completed with counts by kind.
    assert len(await _audits(world, a, "audit.subject_erased")) == 1
    (completed,) = await _audits(world, a, "person.erasure_completed")
    assert completed["details"]["erasure_id"] == str(erasure_id)
    assert completed["details"]["files_deleted"] == 1
    assert completed["details"]["files_kept"] == 1
    # Events: status_changed with reason erasure, then the completion.
    statuses = await _events(world, a, "identity_access.user.status_changed")
    assert {
        "user_id": str(a.tech_a),
        "status": "disabled",
        "reason": "erasure",
        "source": None,
    } in (statuses)
    assert await _events(world, a, "identity_access.person_erasure.completed") == [
        {"person_id": str(a.tech_a), "erasure_id": str(erasure_id)}
    ]
    # Everyone else untouched: tech_b here, and the other tenant.
    assert (await _counts(world, a, a.tech_b))["live_keys"] == 1
    assert (await _counts(world, a, a.tech_b))["live_files"] == 1
    assert await _counts(world, b, b.tech_a) == before_b
    other = await _one(world, "SELECT status FROM users WHERE id = $1", b.tech_a)
    assert other == "active"

    # Run again: nothing changes, nothing is called, no event is written.
    outbox = await _one(world, "SELECT count(*) FROM outbox_events WHERE tenant_id = $1", a.tenant)
    again = Effects()
    outcome = await _run(world, a, erasure_id, again)
    assert (outcome.state, outcome.step) == ("done", 8)
    assert (again.mail, again.ended, again.keycloak.calls) == ([], [], [])
    assert (
        await _one(world, "SELECT count(*) FROM outbox_events WHERE tenant_id = $1", a.tenant)
        == outbox
    )


async def test_ports_are_idempotent_on_their_own(world: World) -> None:
    """A second call of every lane B port changes nothing and counts nothing (ADR-052 §4)."""
    a = world.a
    await _seed(world, a)
    now = datetime.now(UTC)
    for round_ in (1, 2):
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            for port in registered_ports():
                batch = await port.erase_person(
                    session, a.tech_a, successor_id=a.tech_c, keep_files={}, now=now, cursor=None
                )
                assert batch.cursor is None
                if round_ == 2:
                    assert sum(batch.counts.values()) == 0, (port.module, batch.counts)


async def test_a_failing_step_rolls_back_records_a_code_and_resumes_there(world: World) -> None:
    a = world.a
    await _seed(world, a)
    erasure_id = await _approved(world, a, a.tech_a)
    down = Effects(FakeKeycloak(down=True))
    outcome = await _run(world, a, erasure_id, down)
    assert (outcome.state, outcome.step, outcome.error_code) == (
        "running",
        3,
        "erasure_identity_unavailable",
    )
    row = await _row(world, a, erasure_id)
    assert (row["attempts"], row["last_error_code"]) == (1, "erasure_identity_unavailable")
    assert down.mail != []  # steps 1 and 2 committed before Keycloak failed
    # Frozen meanwhile: no access while it waits.
    assert await _one(world, "SELECT status FROM users WHERE id = $1", a.tech_a) == "disabled"

    up = Effects()
    outcome = await _run(world, a, erasure_id, up)
    assert (outcome.state, outcome.step) == ("done", 8)
    assert up.mail == []  # resumed at step 3: the mail step did not run again
    assert up.ended == []
    assert ("remove_member", f"sub-{a.tech_a}") in up.keycloak.calls
    row = await _row(world, a, erasure_id)
    assert (row["attempts"], row["last_error_code"]) == (0, None)


async def test_an_account_other_tenants_have_is_kept(world: World) -> None:
    a = world.a
    erasure_id = await _approved(world, a, a.tech_a)
    effects = Effects(FakeKeycloak(others=[str(world.b.tenant)]))
    assert (await _run(world, a, erasure_id, effects)).state == "done"
    assert ("delete_user", f"sub-{a.tech_a}") not in effects.keycloak.calls
    assert ("remove_member", f"sub-{a.tech_a}") in effects.keycloak.calls


async def test_a_missing_required_port_stops_the_job_and_is_audited(world: World) -> None:
    a = world.a
    erasure_id = await _approved(world, a, a.tech_a)
    files = next(p for p in registered_ports() if p.module == "files")
    unregister_person_data("files")
    try:
        assert person_data.missing_ports() == ["files"]
        outcome = await _run(world, a, erasure_id, Effects())
    finally:
        register_person_data(files)
    assert (outcome.state, outcome.step, outcome.error_code) == (
        "failed",
        0,
        "erasure_port_missing",
    )
    (failed,) = await _audits(world, a, "person.erasure_failed")
    assert failed["reason_code"] == "erasure_port_missing"
    assert failed["details"]["missing_ports"] == ["files"]
    assert await _one(world, "SELECT status FROM users WHERE id = $1", a.tech_a) == "active"
    # Failed stays open: no second erasure may start for a possibly half-erased person.
    assert (await _row(world, a, erasure_id))["state"] == "failed"


async def test_a_person_held_at_job_start_is_refused(world: World) -> None:
    a = world.a
    erasure_id = await _approved(world, a, a.tech_a)
    await world.sql(
        "UPDATE users SET legal_hold_at = now(), legal_hold_reason = 'Court order'"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        a.tech_a,
    )
    effects = Effects()
    outcome = await _run(world, a, erasure_id, effects)
    assert (outcome.state, outcome.error_code) == ("failed", "person_on_legal_hold")
    assert (effects.mail, effects.ended, effects.keycloak.calls) == ([], [], [])
    assert await _one(world, "SELECT status FROM users WHERE id = $1", a.tech_a) == "active"
    (failed,) = await _audits(world, a, "person.erasure_failed")
    assert failed["reason_code"] == "person_on_legal_hold"


async def test_a_successor_who_left_is_replaced_by_the_approver(world: World) -> None:
    a = world.a
    erasure_id = await _approved(world, a, a.tech_a)
    await world.sql(
        "UPDATE users SET status = 'disabled' WHERE tenant_id = $1 AND id = $2", a.tenant, a.tech_c
    )
    assert (await _run(world, a, erasure_id, Effects())).state == "done"
    row = await _row(world, a, erasure_id)
    assert row["effective_successor_id"] == a.lead
    assert json.loads(row["counts"])["successor_replaced"] == 1


async def test_ports_run_in_batches_each_committed(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A port that returns a cursor is called again in a new transaction, from the cursor."""
    a = world.a
    seen: list[str | None] = []

    class Batched:
        module: ClassVar[str] = "test_batched"
        order: ClassVar[int] = 150

        async def erase_person(
            self,
            session: object,
            person_id: uuid.UUID,
            *,
            successor_id: uuid.UUID,
            keep_files: Mapping[uuid.UUID, str],
            now: datetime,
            cursor: str | None,
        ) -> ErasureBatch:
            del session, person_id, successor_id, keep_files, now
            seen.append(cursor)
            nxt = {None: "page-2", "page-2": "page-3"}.get(cursor)
            return ErasureBatch({"test_rows": 1}, nxt)

    register_person_data(cast("PersonData", Batched()))
    try:
        erasure_id = await _approved(world, a, a.tech_a)
        steps: list[tuple[int, str | None, str | None]] = []
        real = erasure_job._one_step  # noqa: SLF001 - observing each committed transaction

        async def watched(*args: Any) -> Any:  # noqa: ANN401 - passed on
            result = await real(*args)
            row = await _row(world, a, erasure_id)
            steps.append((row["step"], row["port_module"], row["port_cursor"]))
            return result

        monkeypatch.setattr(erasure_job, "_one_step", watched)
        assert (await _run(world, a, erasure_id, Effects())).state == "done"
    finally:
        unregister_person_data("test_batched")
    assert seen == [None, "page-2", "page-3"]
    assert (4, "test_batched", "page-2") in steps
    assert (4, "test_batched", "page-3") in steps
    assert json.loads((await _row(world, a, erasure_id))["counts"])["test_rows"] == 3
