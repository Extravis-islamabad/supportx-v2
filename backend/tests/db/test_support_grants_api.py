"""Vendor support grants (WP-057 S4c-1, REQ-SEC-045, D-173), against a real database.

- A grant makes a temporary account under a generated login (D-177), in the tenant's
  organization, with a complete profile the engineer can never edit: its own verified .invalid
  address, both names, and no default roles (lane B's conditions on #566). Out of band, the
  admin sees a one-time password once, never again (not in the replay, not in the database, not
  in the audit).
- With mail (D-177), no credential exists until the engineer's own mailbox sets one, with MFA.
- D-173's rules refuse: another domain, a fourth open grant, the opt-out; the opt-out is refused
  while a grant is open; only tenant admins act.
- Ending a grant refuses the account at once; its Keycloak account is disabled, then deleted, and
  the removal counts only once confirmed: a failed delete is retried by the schedule.
- A support account never holds an API key, and its type never changes.
- Another tenant sees none of it, and its schedule pass touches none of it.
"""

import dataclasses
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest
from pydantic import SecretStr

from app.core.database import Database, create_engine
from app.modules.identity_access.domain import support_grants as rules
from app.modules.identity_access.infra.crypto import SessionCipher
from app.modules.identity_access.infra.keycloak_admin import IdentityAdminUnavailable
from app.modules.identity_access.infra.store import SessionStore
from app.modules.identity_access.service import password_reset, support_grant_job, support_grants
from app.modules.identity_access.tests.fake_idp import MemoryKeyValue
from tests.app_state import set_state
from tests.db.test_identity_api import World, world  # noqa: F401 - the fixture, reused

pytestmark = pytest.mark.db

BASE = "/identity/vendor-support"


def _body(**changes: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {
        "engineer_name": "Omar Engineer",
        "engineer_email": "omar@extravis.com",
        "reason": "A workflow is stuck on INC-12",
        "ticket_ref": "EXT-1042",
        "verification": "out_of_band",
        "confirmation_note": "Called Extravis support back on the published number",
        **changes,
    }


async def _grant(world: World, key: str | None = None, **changes: Any) -> Any:  # noqa: F811, ANN401
    return await world.call(
        "POST",
        f"{BASE}/grants",
        world.a,
        json=_body(**changes),
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
    )


async def _audited(world: World, code: str) -> int:  # noqa: F811 - the reused fixture
    """How many audit entries of `code` the tenant has (the SECURITY chain, lane B)."""
    rows = await _sql(
        world,
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        world.a.tenant,
        code,
    )
    return int(rows[0]["n"])


async def _sql(world: World, statement: str, *args: Any) -> list[asyncpg.Record]:  # noqa: F811, ANN401
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        return list(await conn.fetch(statement, *args))
    finally:
        await conn.close()


async def _account(world: World, grant_id: uuid.UUID | str) -> tuple[str, uuid.UUID]:  # noqa: F811 - the reused fixture
    """The grant's Keycloak account ID and its local user ID."""
    (row,) = await _sql(
        world,
        "SELECT u.external_subject, u.id FROM support_grants g"
        " JOIN users u ON u.tenant_id = g.tenant_id AND u.id = g.support_user_id WHERE g.id = $1",
        uuid.UUID(str(grant_id)),
    )
    return str(row["external_subject"]), row["id"]


async def test_an_out_of_band_grant_shows_its_password_once_and_makes_a_support_account(
    world: World,  # noqa: F811 - the reused fixture
) -> None:
    key = str(uuid.uuid4())
    made = await _grant(world, key)
    assert made.status_code == 201, made.text
    body = made.json()
    password = body["one_time_password"]
    assert password
    assert len(password) >= 20
    assert body["state"] == "pending_verification"  # "waiting for the engineer" (lane B (12))
    assert body["admin_could_act"] is True  # out of band: the admin held a credential
    assert made.headers["cache-control"] == "no-store"
    # The replay (same Idempotency-Key) makes nothing new and never carries the password.
    again = await _grant(world, key)
    assert again.status_code == 201, again.text
    assert again.json()["id"] == body["id"]
    assert again.json()["one_time_password"] is None
    # The account: a generated login in the tenant's organization (D-177), its profile complete
    # (a .invalid verified address, both names) so a fresh realm asks the engineer for nothing
    # but a password and a code, and no default roles, so it can never change itself.
    grant_id = uuid.UUID(body["id"])
    account, user_id = await _account(world, grant_id)
    assert world.admin.required[account] == list(rules.FIRST_SIGN_IN_ACTIONS)  # nothing else
    assert account in world.admin.temporary_passwords  # Keycloak makes them choose their own
    address = rules.support_address(grant_id)
    assert world.admin.usernames == {rules.support_login(grant_id): address}
    assert world.admin.verified[address] is True
    assert world.admin.names[account] == ("Omar", "Engineer")  # the named engineer (D-180)
    assert account in world.admin.without_default_roles
    rows = await _sql(
        world,
        "SELECT user_type, email, can_sign_in, display_name FROM users"
        " WHERE tenant_id = $1 AND id = $2",
        world.a.tenant,
        user_id,
    )
    # D-178: wherever it acts, the account is "Extravis support"; the grant names the engineer.
    assert [(r["user_type"], r["email"], r["can_sign_in"], r["display_name"]) for r in rows] == [
        ("vendor_support", None, True, "Extravis support")
    ]
    # The password is nowhere: not the grant, not its history, not the audit.
    for table in ("support_grants", "audit_entries", "field_changes"):
        dump = await _sql(world, f"SELECT row_to_json(t)::text AS j FROM {table} t")  # noqa: S608 - fixed names
        assert all(password not in r["j"] for r in dump), table


async def test_the_actions_email_path_holds_no_credential(
    world: World,  # noqa: F811 - the reused fixture
) -> None:
    """D-177: with mail, no password exists; the engineer's own mailbox sets one, with MFA."""
    made = await _grant(world, verification="email", confirmation_note=None)
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["one_time_password"] is None
    assert body["admin_could_act"] is False
    grant_id = uuid.UUID(body["id"])
    account, _ = await _account(world, grant_id)
    assert account not in world.admin.passwords_set  # no credential before the link (8)
    assert world.admin.emails == []  # Keycloak sends nothing: its address is .invalid
    (mail,) = await _sql(
        world,
        "SELECT recipients, subject, text_body, kind FROM mail_messages WHERE tenant_id = $1",
        world.a.tenant,
    )
    assert list(mail["recipients"]) == ["omar@extravis.com"]
    assert mail["kind"] == "vendor_support_link"
    assert rules.mail_subject_id(grant_id) in mail["subject"]
    assert rules.support_login(grant_id) in mail["text_body"]
    # The console page itself, one slash after the origin: the branded console URL ends with "/",
    # and a doubled one opened the sign-in instead of the page (lane C's fresh-stack e2e).
    (link,) = re.findall(r"https?://\S+/vendor-support/start\S*", str(mail["text_body"]))
    assert "//vendor-support" not in link, link
    (grant,) = await _sql(
        world, "SELECT link_token_hash, link_expires_at FROM support_grants WHERE id = $1", grant_id
    )
    assert grant["link_token_hash"] is not None
    assert bytes(grant["link_token_hash"]).hex() not in mail["text_body"]  # only the hash kept


async def test_the_d173_rules_refuse(world: World) -> None:  # noqa: F811 - the reused fixture
    other = await _grant(world, engineer_email="omar@gmail.com")
    assert other.status_code == 422, other.text
    assert {e["code"] for e in other.json()["errors"]} == {"support_email_domain_not_allowed"}
    for n in range(3):
        made = await _grant(world, engineer_email=f"eng{n}@extravis.com")
        assert made.status_code == 201, made.text
    fourth = await _grant(world, engineer_email="eng9@extravis.com")
    assert fourth.status_code == 422, fourth.text
    assert "support_grants_limit" in {e["code"] for e in fourth.json()["errors"]}
    # The opt-out is refused while grants are open.
    setting = (await world.call("GET", f"{BASE}/setting", world.a)).json()
    blocked = await world.call(
        "PUT",
        f"{BASE}/setting",
        world.a,
        json={"never_allow": True},
        headers={"If-Match": f'"{setting["version"]}"'},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "vendor_support_grants_open"


async def test_the_opt_out_refuses_every_grant(world: World) -> None:  # noqa: F811 - the reused fixture
    setting = (await world.call("GET", f"{BASE}/setting", world.a)).json()
    on = await world.call(
        "PUT",
        f"{BASE}/setting",
        world.a,
        json={"never_allow": True},
        headers={"If-Match": f'"{setting["version"]}"'},
    )
    assert on.status_code == 200, on.text
    refused = await _grant(world)
    assert refused.status_code == 422, refused.text
    assert "vendor_support_disabled" in {e["code"] for e in refused.json()["errors"]}


async def test_only_tenant_admins_see_or_grant(world: World) -> None:  # noqa: F811 - the reused fixture
    for user in (world.a.manager, world.a.tech, world.a.requester):
        listed = await world.call("GET", f"{BASE}/grants", world.a, user=user)
        assert listed.status_code == 403, listed.text


async def test_ending_refuses_at_once_then_disables_and_deletes_the_account(world: World) -> None:  # noqa: F811 - the reused fixture
    body = (await _grant(world)).json()
    grant_id = body["id"]
    kc, _ = await _account(world, grant_id)
    ended = await world.call("POST", f"{BASE}/grants/{grant_id}/revoke", world.a)
    assert ended.status_code == 200, ended.text
    assert ended.json()["state"] == "revoked"
    (user,) = await _sql(
        world, "SELECT status, can_sign_in FROM users WHERE external_subject = $1", kc
    )
    assert (user["status"], user["can_sign_in"]) == ("disabled", False)
    assert world.admin.enabled[kc] is False  # disabled before the delete (lane B (5))
    assert kc not in world.admin.accounts
    (grant,) = await _sql(
        world, "SELECT account_removed_at FROM support_grants WHERE id = $1", uuid.UUID(grant_id)
    )
    assert grant["account_removed_at"] is not None  # confirmed, so recorded
    again = await world.call("POST", f"{BASE}/grants/{grant_id}/revoke", world.a)
    assert again.status_code == 200, again.text  # idempotent


async def test_a_failed_delete_is_not_done_and_the_schedule_retries_it(
    world: World,  # noqa: F811 - the reused fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lane B: a failure never counts as removed; the sweep retries until Keycloak confirms."""
    body = (await _grant(world)).json()
    grant_id = uuid.UUID(body["id"])
    real_delete = world.admin.delete_user
    calls = {"n": 0}

    async def flaky(user_id: str) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise IdentityAdminUnavailable
        await real_delete(user_id)

    monkeypatch.setattr(world.admin, "delete_user", flaky)
    await world.call("POST", f"{BASE}/grants/{grant_id}/revoke", world.a)
    (grant,) = await _sql(
        world, "SELECT account_removed_at FROM support_grants WHERE id = $1", grant_id
    )
    assert grant["account_removed_at"] is None  # not done
    assert await _audited(world, "support_grant.account_removal_failed") == 1
    (entry,) = await _sql(
        world,
        "SELECT details::text AS d FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        world.a.tenant,
        "support_grant.account_removal_failed",
    )
    assert "IdentityAdminUnavailable" in entry["d"]  # the error's class only
    # Five minutes later (the retry spacing), the schedule tries again and it is confirmed.
    await _sql(
        world,
        "UPDATE support_grants SET updated_at = now() - interval '6 minutes' WHERE id = $1",
        grant_id,
    )
    await _run_schedule(world)
    (grant,) = await _sql(
        world, "SELECT account_removed_at FROM support_grants WHERE id = $1", grant_id
    )
    assert grant["account_removed_at"] is not None
    assert calls["n"] == 2


async def _run_schedule(world: World) -> None:  # noqa: F811 - the reused fixture
    engine = create_engine(world.db.app_url, application_name="test")
    try:
        database = Database(engine)
        for tenant in (world.a.tenant, world.b.tenant):
            await support_grant_job.run_tenant(
                database, tenant, admin=world.admin, end_sessions=None
            )
    finally:
        await engine.dispose()


async def test_the_schedule_ends_an_expired_grant_in_its_own_tenant_only(world: World) -> None:  # noqa: F811 - the reused fixture
    body = (await _grant(world, hours=1)).json()
    grant_id = uuid.UUID(body["id"])
    past = datetime.now(UTC) - timedelta(minutes=1)
    await _sql(
        world,
        "UPDATE support_grants SET starts_at = $2::timestamptz - interval '1 hour', ends_at = $2"
        " WHERE id = $1",
        grant_id,
        past,
    )
    await _run_schedule(world)
    (grant,) = await _sql(
        world, "SELECT state, account_removed_at FROM support_grants WHERE id = $1", grant_id
    )
    assert grant["state"] == "ended"
    assert grant["account_removed_at"] is not None
    assert await _audited(world, "support_grant.ended") == 1  # the system's, nobody clicked
    assert await _audited(world, "support_grant.account_removed") == 1
    # Tenant B sees none of it.
    listed = await world.call("GET", f"{BASE}/grants", world.b)
    assert listed.status_code == 200, listed.text
    assert listed.json() == []


async def test_a_support_account_never_holds_a_key_and_its_type_never_changes(
    world: World,  # noqa: F811 - the reused fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = world.app.state.settings
    keyed = settings.model_copy(update={"api_key_secret": SecretStr("k" * 48)})
    set_state(monkeypatch, world.app.state, "settings", keyed)  # keys can be made at all
    body = (await _grant(world)).json()
    _, user_id = await _account(world, body["id"])
    (row,) = await _sql(world, "SELECT id, version FROM users WHERE id = $1", user_id)
    support_user = row["id"]
    key = await world.call(
        "POST",
        "/api-keys",
        world.a,
        user=support_user,
        json={"name": "Mine", "scopes": ["incidents.view"]},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert key.status_code == 403, key.text
    assert key.json()["code"] == "api_key_vendor_support"
    retyped = await world.call(
        "PUT",
        f"/users/{support_user}/type",
        world.a,
        json={"user_type": "technician"},
        headers={"If-Match": f'"{row["version"]}"'},
    )
    assert retyped.status_code in {404, 409}, retyped.text
    if retyped.status_code == 409:
        assert retyped.json()["code"] == "vendor_support_type_fixed"


async def test_a_support_account_never_signs_in_through_an_identity_provider(
    world: World,  # noqa: F811 - the reused fixture
) -> None:
    """Lane B (10): a tenant's provider could be linked to the account by Keycloak's broker."""
    body = (await _grant(world)).json()
    kc, _ = await _account(world, body["id"])
    engine = create_engine(world.db.app_url, application_name="test")
    try:
        database = Database(engine)
        brokered = await support_grants.sign_in_refusal(
            database, world.a.tenant, kc, None, identity_provider="acme-oidc"
        )
        own = await support_grants.sign_in_refusal(database, world.a.tenant, kc, None)
    finally:
        await engine.dispose()
    assert brokered == support_grants.BROKERED
    assert own is None  # its own password and second factor, within its grant


async def test_no_log_line_holds_the_password_or_the_engineers_addresses(
    world: World,  # noqa: F811 - the reused fixture
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D-173 / lane B (6): the credential and the engineer's personal data never reach a log."""
    caplog.set_level(logging.DEBUG)
    made = await _grant(world)
    assert made.status_code == 201, made.text
    body = made.json()
    ended = await world.call("POST", f"{BASE}/grants/{body['id']}/revoke", world.a)
    assert ended.status_code == 200, ended.text
    secret = body["one_time_password"]
    logged = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert caplog.records  # something was logged at all
    for private in (secret, "omar@extravis.com"):
        assert private not in logged


async def test_a_support_account_is_never_in_the_people_list(
    world: World,  # noqa: F811 - the reused fixture
) -> None:
    """D-173 design (8): no people list, picker or count shows a vendor support account."""
    body = (await _grant(world)).json()
    _, user_id = await _account(world, body["id"])
    (row,) = await _sql(world, "SELECT id FROM users WHERE id = $1", user_id)
    listed = await world.call("GET", "/users", world.a, params={"limit": 200})
    assert listed.status_code == 200, listed.text
    assert str(row["id"]) not in listed.text
    assert "Omar Engineer" not in listed.text
    edited = await world.call(
        "PATCH",
        f"/users/{row['id']}/person",
        world.a,
        json={"first_name": "Someone"},
        headers={"If-Match": '"1"'},
    )
    assert edited.status_code == 409, edited.text  # the people screens never change it


async def test_a_support_account_never_gets_a_role_a_group_or_any_permission(
    world: World,  # noqa: F811 - the reused fixture
) -> None:
    """Lane B: never tenant admin or security; its access is its grant's alone (fails closed)."""
    body = (await _grant(world)).json()
    _, user_id = await _account(world, body["id"])
    (admin_role,) = await _sql(
        world, "SELECT id FROM roles WHERE tenant_id = $1 AND key = 'tenant_admin'", world.a.tenant
    )
    role = await world.call("PUT", f"/users/{user_id}/roles/{admin_role['id']}", world.a)
    assert role.status_code == 403, role.text
    assert role.json()["code"] == "vendor_support_roles_from_grant"
    group = await world.call(
        "POST",
        "/organization/groups",
        world.a,
        json={"name": "Support desk"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert group.status_code == 201, group.text
    joined = await world.call(
        "PUT", f"/organization/groups/{group.json()['id']}/members/{user_id}", world.a
    )
    assert joined.status_code == 403, joined.text
    assert joined.json()["code"] == "vendor_support_roles_from_grant"
    # Even a role put there behind the API's back gives it nothing (the compile ceiling).
    await _sql(
        world,
        "INSERT INTO user_roles (tenant_id, user_id, role_id) VALUES ($1, $2, $3)",
        world.a.tenant,
        user_id,
        admin_role["id"],
    )
    seen = await world.call("GET", "/identity/vendor-support/grants", world.a, user=user_id)
    assert seen.status_code == 403, seen.text


async def _mailed_token(world: World, grant_id: str) -> str:  # noqa: F811 - the reused fixture
    """The newest link's token, read from the mail's link fragment (as the engineer would)."""
    rows = await _sql(
        world,
        "SELECT text_body FROM mail_messages WHERE tenant_id = $1 AND subject LIKE $2"
        " ORDER BY created_at DESC LIMIT 1",
        world.a.tenant,
        f"%{rules.mail_subject_id(uuid.UUID(grant_id))}%",
    )
    return str(rows[0]["text_body"]).split("#", 1)[1].split()[0]


async def _open(world: World, token: str) -> Any:  # noqa: ANN401, F811 - the reused fixture
    return await world.client.post(
        "/api/v1/public/vendor-support/open",
        json={"token": token, "tenant": await _slug_of(world)},
    )


async def _slug_of(world: World) -> str:  # noqa: F811 - the reused fixture
    (row,) = await _sql(world, "SELECT slug FROM tenants WHERE id = $1", world.a.tenant)
    return str(row["slug"])


async def test_the_link_opens_once_and_every_failure_looks_the_same(
    world: World,  # noqa: F811 - the reused fixture
) -> None:
    """Lane B (1)-(3): only the POST spends it; once; unknown, used and expired answer alike."""
    body = (await _grant(world, verification="email", confirmation_note=None)).json()
    token = await _mailed_token(world, body["id"])
    account, _ = await _account(world, body["id"])
    # Following the link changes nothing: there is no GET to spend it.
    probe = await world.client.get("/api/v1/public/vendor-support/open")
    assert probe.status_code == 405, probe.text
    assert account not in world.admin.passwords_set
    opened = await _open(world, token)
    assert opened.status_code == 200, opened.text
    assert opened.headers["cache-control"] == "no-store"
    assert opened.headers["referrer-policy"] == "no-referrer"  # the API's own (S4c-3, lane B)
    assert "default-src 'none'" in opened.headers["content-security-policy"]
    assert opened.json()["login"] == rules.support_login(uuid.UUID(body["id"]))
    assert account in world.admin.temporary_passwords  # Keycloak makes them choose their own
    again = await _open(world, token)
    wrong = await _open(world, "x" * 43)
    assert again.status_code == wrong.status_code == 404
    assert again.json()["code"] == wrong.json()["code"] == "support_link_invalid"
    assert again.json()["message_key"] == wrong.json()["message_key"]
    (grant,) = await _sql(
        world,
        "SELECT link_token_hash, link_used_at FROM support_grants WHERE id = $1",
        uuid.UUID(body["id"]),
    )
    assert grant["link_token_hash"] is None
    assert grant["link_used_at"] is not None
    assert await _audited(world, "support_grant.link_opened") == 1  # the failures add none


async def test_a_resent_link_kills_the_old_one_and_an_expired_one_opens_nothing(
    world: World,  # noqa: F811 - the reused fixture
) -> None:
    body = (await _grant(world, verification="email", confirmation_note=None)).json()
    first = await _mailed_token(world, body["id"])
    resent = await world.call("POST", f"{BASE}/grants/{body['id']}/resend-link", world.a)
    assert resent.status_code == 200, resent.text
    second = await _mailed_token(world, body["id"])
    assert first != second
    assert (await _open(world, first)).status_code == 404  # the old one is dead
    # The new one, left to expire: the schedule clears it, and it opens nothing.
    await _sql(
        world,
        "UPDATE support_grants SET link_expires_at = now() - interval '1 minute' WHERE id = $1",
        uuid.UUID(body["id"]),
    )
    await _run_schedule(world)
    (grant,) = await _sql(
        world, "SELECT link_token_hash FROM support_grants WHERE id = $1", uuid.UUID(body["id"])
    )
    assert grant["link_token_hash"] is None
    assert (await _open(world, second)).status_code == 404
    assert await _audited(world, "support_grant.link_expired") == 1


async def test_the_first_sign_in_is_audited_with_how_the_engineer_was_verified(
    world: World,  # noqa: F811 - the reused fixture
) -> None:
    """Lane B (11): a review can tell which grants an admin could have used."""
    body = (await _grant(world)).json()
    _, user_id = await _account(world, body["id"])
    engine = create_engine(world.db.app_url, application_name="test")
    try:
        await support_grants.mark_first_use(Database(engine), world.a.tenant, user_id)
    finally:
        await engine.dispose()
    (entry,) = await _sql(
        world,
        "SELECT details::text AS d FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        world.a.tenant,
        "support_grant.first_used",
    )
    assert "out_of_band" in entry["d"]


async def test_an_open_session_is_cut_on_revoke_and_on_expiry(
    world: World,  # noqa: F811 - the reused fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lane B (4), (4b): the store marker and Centrifugo's disconnect, both ways a grant ends."""
    cut: list[tuple[uuid.UUID, uuid.UUID]] = []

    class Auth:
        async def end_sessions(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
            cut.append((tenant_id, user_id))

    set_state(monkeypatch, world.app.state, "auth", Auth())
    revoked = (await _grant(world, engineer_email="eng1@extravis.com")).json()
    _, revoked_user = await _account(world, revoked["id"])
    ended = await world.call("POST", f"{BASE}/grants/{revoked['id']}/revoke", world.a)
    assert ended.status_code == 200, ended.text
    assert cut == [(world.a.tenant, revoked_user)]  # revoke: cut after the commit
    expiring = (await _grant(world, engineer_email="eng2@extravis.com")).json()
    _, expiring_user = await _account(world, expiring["id"])
    await _sql(
        world,
        "UPDATE support_grants SET starts_at = now() - interval '2 hours',"
        " ends_at = now() - interval '1 minute' WHERE id = $1",
        uuid.UUID(expiring["id"]),
    )

    async def ender(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        cut.append((tenant_id, user_id))

    engine = create_engine(world.db.app_url, application_name="test")
    try:
        await support_grant_job.run_tenant(
            Database(engine), world.a.tenant, admin=world.admin, end_sessions=ender
        )
    finally:
        await engine.dispose()
    assert cut[-1] == (world.a.tenant, expiring_user)  # expiry: the schedule cuts it too


async def test_a_support_account_never_gets_a_password_reset(
    world: World,  # noqa: F811 - the reused fixture
) -> None:
    """Lane B's condition 7 on #566: its grant is its only way in, and the answer is the same.

    Decided by the account's own row (not its address): the reset sends nothing and changes no
    required action, while a staff account in the same tenant gets its e-mail (the control).
    """
    made = await _grant(world)
    assert made.status_code == 201, made.text
    grant_id = uuid.UUID(made.json()["id"])
    account, _ = await _account(world, grant_id)
    address = rules.support_address(grant_id)
    # As after its first sign-in: a password of its own, so only the account's kind refuses it.
    world.admin.accounts[account] = dataclasses.replace(
        world.admin.accounts[account], has_password=True
    )
    required = list(world.admin.required[account])
    database = Database(create_engine(world.db.app_url, application_name="test"))
    store = SessionStore(MemoryKeyValue(), SessionCipher("x" * 40))
    settings = world.app.state.settings
    world.admin.emails.clear()
    await password_reset.request_reset(
        database, settings, store, world.admin, password_reset.ResetRequest(address, None, None)
    )
    assert world.admin.emails == []
    assert world.admin.required[account] == required
    # The control: staff in the same tenant and organization get the reset e-mail.
    org = world.admin.orgs[str(world.a.tenant)]
    world.admin.accounts["kc-staff"] = dataclasses.replace(
        world.admin.accounts[account], id="kc-staff", email="staff@acme.test"
    )
    world.admin.members.setdefault(org.id, set()).add("kc-staff")
    await _sql(
        world,
        "UPDATE users SET external_subject = 'kc-staff', email = 'staff@acme.test' WHERE id = $1",
        world.a.tech,
    )
    await password_reset.request_reset(
        database,
        settings,
        store,
        world.admin,
        password_reset.ResetRequest("staff@acme.test", None, None),
    )
    assert world.admin.emails == [("kc-staff", ["UPDATE_PASSWORD"], 3600)]
