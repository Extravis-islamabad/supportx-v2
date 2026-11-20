"""Vendor support's per-request check costs ordinary sessions nothing (WP-057 S4c-1, lane B (6)).

Every request on a vendor_support session asks its grant (support_grants.request_refusal); every
other session pays one in-memory comparison of its stored user type and never reaches it. Proven
here with a real BFF sign-in: the check is made to fail if anyone ever calls it.
"""

import uuid
from typing import Any

import pytest

from app.modules.identity_access.service import support_grants
from tests.db.test_auth_bff import Bff, bff  # noqa: F401 - the fixture, reused
from tests.db.test_sso_required_sign_in import _email, _provider, _sql

pytestmark = pytest.mark.db


async def test_an_ordinary_session_never_reaches_the_support_check(
    bff: Bff,  # noqa: F811 - the reused fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def never(*_args: Any, **_kwargs: Any) -> None:  # noqa: ANN401 - any arguments
        message = "an ordinary session reached the vendor support check"
        raise AssertionError(message)

    monkeypatch.setattr(support_grants, "request_refusal", never)
    assert (await bff.login(bff.user("a"))).status_code == 302
    for _ in range(20):
        me = await bff.me()
        assert me.status_code == 200, me.text


async def test_a_brokered_support_sign_in_is_refused_before_the_link_audit_or_provisioning(
    bff: Bff,  # noqa: F811 - the reused fixture
) -> None:
    """The coordinator, after #556 merged beside #552: both checks, in order.

    A vendor support account signing in through the tenant's own provider is refused by the
    support check (`support_sign_in_brokered`) before #556's link audit runs or the account is
    touched; its own sign-in (no provider) still gets in, the control.
    """
    a, _b = bff.tenants
    await _provider(bff.db, a, "a-sup-idp")
    email = _email("support")
    own = bff.user("a", email=email)
    assert (await bff.login(own)).status_code == 302  # the account exists (made by its sign-in)
    (row,) = await _sql(
        bff.db, "SELECT id FROM users WHERE tenant_id = $1 AND email = $2", a, email
    )
    user_id = row["id"]
    # Made a vendor support account with an open grant, as #552 makes them.
    await _sql(
        bff.db,
        "UPDATE users SET user_type = 'vendor_support', roles_mapped_at = now() WHERE id = $1",
        user_id,
    )
    await _sql(
        bff.db,
        "INSERT INTO support_grants (id, tenant_id, engineer_name, engineer_email, reason, access,"
        " starts_at, ends_at, state, verification, support_user_id)"
        " VALUES ($1, $2, 'Omar', 'omar@extravis.com', 'r', 'view', now() - interval '1 hour',"
        " now() + interval '1 hour', 'active', 'email', $3)",
        uuid.uuid4(),
        a,
        user_id,
    )
    before = await _sql(bff.db, "SELECT last_login_at FROM users WHERE id = $1", user_id)
    links_before = await _sql(
        bff.db,
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'identity_provider.account_linked'",
        a,
    )
    brokered = bff.user("a", email=email, identity_provider="a-sup-idp")
    refused = await bff.login(brokered)
    assert (refused.status_code, refused.json()["code"]) == (403, "support_sign_in_brokered")
    # Refused first: no link audited, the account untouched, the refusal logged.
    links_after = await _sql(
        bff.db,
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'identity_provider.account_linked'",
        a,
    )
    assert links_after[0]["n"] == links_before[0]["n"]
    after = await _sql(bff.db, "SELECT last_login_at FROM users WHERE id = $1", user_id)
    assert after[0]["last_login_at"] == before[0]["last_login_at"]
    logged = await _sql(
        bff.db,
        "SELECT reason FROM sign_in_events WHERE tenant_id = $1 AND reason = $2",
        a,
        "support_sign_in_brokered",
    )
    assert logged


async def test_a_support_sessions_write_is_audited_as_extravis_support_with_its_grant(
    bff: Bff,  # noqa: F811 - the reused fixture
) -> None:
    """Lane B (7), D-178: a vendor support account's save names "Extravis support" and the grant."""
    a, _b = bff.tenants
    asker_email = _email("requester")
    requester = bff.user("a", email=asker_email)
    assert (await bff.login(requester)).status_code == 302
    email = _email("support-writes")
    assert (await bff.login(bff.user("a", email=email))).status_code == 302
    (row,) = await _sql(
        bff.db, "SELECT id FROM users WHERE tenant_id = $1 AND email = $2", a, email
    )
    (asker,) = await _sql(
        bff.db, "SELECT id FROM users WHERE tenant_id = $1 AND email = $2", a, asker_email
    )
    user_id, grant_id = row["id"], uuid.uuid4()
    await _sql(
        bff.db,
        "UPDATE users SET user_type = 'vendor_support', roles_mapped_at = now() WHERE id = $1",
        user_id,
    )
    # As #552 makes them: no role at all (its first sign-in here gave it one).
    await _sql(bff.db, "DELETE FROM user_roles WHERE tenant_id = $1 AND user_id = $2", a, user_id)
    await _sql(
        bff.db,
        "INSERT INTO support_grants (id, tenant_id, engineer_name, engineer_email, reason, access,"
        " change_reason, starts_at, ends_at, state, verification, support_user_id)"
        " VALUES ($1, $2, 'Omar', 'omar@extravis.com', 'r', 'view_and_change', 'fix INC-12',"
        " now() - interval '1 hour', now() + interval '1 hour', 'active', 'email', $3)",
        grant_id,
        a,
        user_id,
    )
    # Its own sign-in again, now as the support account (the session keeps the account's type).
    assert (await bff.login(bff.user("a", email=email))).status_code == 302
    # #552's bugs: /auth/me answered 500 for a support account (no vendor_support user type),
    # and the console refused it as requester-only (no role at all); lane B (i).
    me = await bff.client.get("/api/v1/auth/me", headers={"X-SupportX-Client": "console"})
    assert me.status_code == 200, me.text
    assert me.json()["user"]["user_type"] == "vendor_support"
    # S4c-3's banner: the grant, its level and end; never the engineer's contact (condition 3).
    support = me.json()["support"]
    assert set(support) == {"grant_id", "access", "ends_at", "contacts_masked", "names_masked"}
    assert (support["contacts_masked"], support["names_masked"]) == (True, False)  # D-180
    assert (support["grant_id"], support["access"]) == (str(grant_id), "view_and_change")
    assert "omar@extravis.com" not in me.text
    made = await bff.client.post(
        "/api/v1/incidents",
        json={"subject": "Mail is down", "requester_id": str(asker["id"])},
        headers={"X-CSRF-Token": await _csrf(bff), "X-SupportX-Client": "console"},
    )
    assert made.status_code == 201, made.text
    entries = await _sql(
        bff.db,
        "SELECT actor_type, actor_id, details->>'grant_id' AS grant_id FROM audit_entries"
        " WHERE tenant_id = $1 AND object_id = $2",
        a,
        made.json()["id"],
    )
    assert entries
    assert {(e["actor_type"], e["actor_id"], e["grant_id"]) for e in entries} == {
        ("vendor_support", user_id, str(grant_id))
    }


async def _csrf(bff: Bff) -> str:  # noqa: F811 - the reused fixture
    me = await bff.me()
    assert me.status_code == 200, me.text
    return str(me.json()["csrf_token"])


async def _support_session(bff: Bff, *, unmask: bool = False) -> tuple[uuid.UUID, str, str]:  # noqa: F811 - the reused fixture
    """A requester, then a support account (no role, an open view-and-change grant) signed in.

    Returns the requester's ID, name and e-mail.
    """
    a, _b = bff.tenants
    asker_email = _email("asker")
    assert (await bff.login(bff.user("a", email=asker_email))).status_code == 302
    (asker,) = await _sql(
        bff.db,
        "SELECT id, display_name FROM users WHERE tenant_id = $1 AND email = $2",
        a,
        asker_email,
    )
    email = _email("masked-support")
    assert (await bff.login(bff.user("a", email=email))).status_code == 302
    (row,) = await _sql(
        bff.db, "SELECT id FROM users WHERE tenant_id = $1 AND email = $2", a, email
    )
    await _sql(
        bff.db,
        "UPDATE users SET user_type = 'vendor_support', roles_mapped_at = now() WHERE id = $1",
        row["id"],
    )
    await _sql(bff.db, "DELETE FROM user_roles WHERE tenant_id = $1 AND user_id = $2", a, row["id"])
    await _sql(
        bff.db,
        "INSERT INTO support_grants (id, tenant_id, engineer_name, engineer_email, reason, access,"
        " change_reason, unmask_personal, starts_at, ends_at, state, verification,"
        " support_user_id) VALUES ($1, $2, 'Omar', 'omar@extravis.com', 'r', 'view_and_change',"
        " 'fix INC-12', $4, now() - interval '1 hour', now() + interval '1 hour', 'active',"
        " 'email', $3)",
        uuid.uuid4(),
        a,
        row["id"],
        unmask,
    )
    assert (await bff.login(bff.user("a", email=email))).status_code == 302
    return asker["id"], asker["display_name"], asker_email


async def test_a_support_session_sees_names_but_never_an_address(
    bff: Bff,  # noqa: F811 - the reused fixture
) -> None:
    """D-180 (names shown, e-mail and phone always withheld); lane B's and the coordinator's
    search conditions: a support session's person search matches names only, in the query."""
    asker, name, address = await _support_session(bff)
    console = {"X-SupportX-Client": "console"}
    made = await bff.client.post(
        "/api/v1/incidents",
        json={"subject": "Printer jam", "requester_id": str(asker)},
        headers={"X-CSRF-Token": await _csrf(bff), **console},
    )
    assert made.status_code == 201, made.text
    item = made.json()["id"]
    reads = [
        await bff.client.get(f"/api/v1/incidents/{item}", headers=console),
        await bff.client.get("/api/v1/incidents", headers=console),
        await bff.client.get(f"/api/v1/incidents/{item}/history", headers=console),
        await bff.client.get(f"/api/v1/incidents/{item}/timeline", headers=console),
    ]
    for read in reads:
        assert read.status_code in {200, 404}, read.text  # a route a record type lacks: 404
        assert address not in read.text, read.request.url
    assert reads[0].status_code == 200
    assert name in reads[0].text  # names are shown by default
    local, _, domain = address.partition("@")
    # A person's address, its local part or its domain finds nobody; the name finds them.
    for typed in (address, local, domain):
        found = await bff.client.get(
            "/api/v1/incidents/search", params={"q": typed}, headers=console
        )
        assert found.status_code == 200, found.text
        assert item not in found.text, typed
        picker = await bff.client.get(
            "/api/v1/incidents/assignees", params={"search": typed}, headers=console
        )
        assert picker.status_code == 200, picker.text
        assert address not in picker.text
    by_name = await bff.client.get("/api/v1/incidents/search", params={"q": name}, headers=console)
    assert by_name.status_code == 200, by_name.text
    assert item in by_name.text
    # The same app, the next request a staff member's: addresses are back, and found (control).
    assert (await bff.login(bff.user("a", email=address))).status_code == 302
    staff = await bff.client.get("/api/v1/incidents", headers=console)
    assert staff.status_code == 200, staff.text
    assert address in staff.text
    by_address = await bff.client.get(
        "/api/v1/incidents/search", params={"q": local}, headers=console
    )
    assert item in by_address.text


async def test_an_unmasking_grant_still_never_shows_an_address(
    bff: Bff,  # noqa: F811 - the reused fixture
) -> None:
    """D-180: unmask_personal no longer reaches e-mail or phone (lane B (4))."""
    asker, name, address = await _support_session(bff, unmask=True)
    made = await bff.client.post(
        "/api/v1/incidents",
        json={"subject": "Printer jam", "requester_id": str(asker)},
        headers={"X-CSRF-Token": await _csrf(bff), "X-SupportX-Client": "console"},
    )
    assert made.status_code == 201, made.text
    read = await bff.client.get("/api/v1/incidents", headers={"X-SupportX-Client": "console"})
    assert read.status_code == 200, read.text
    assert name in read.text
    assert address not in read.text


async def test_a_support_session_with_no_grant_to_name_is_refused(
    bff: Bff,  # noqa: F811 - the reused fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lane B's #561 review (1): never a support request audited as a plain person."""
    await _support_session(bff)

    def nothing(*_args: Any) -> tuple[None, bool]:  # noqa: ANN401 - any arguments
        return None, False

    monkeypatch.setattr(support_grants, "judged_grant", nothing)
    # Any API route resolves the request's tenant context through the support check.
    listed = await bff.client.get("/api/v1/incidents", headers={"X-SupportX-Client": "console"})
    assert listed.status_code == 401, listed.text
