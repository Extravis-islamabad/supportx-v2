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
