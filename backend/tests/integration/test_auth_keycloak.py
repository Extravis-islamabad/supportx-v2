"""Integration: BFF sign-in against a REAL Keycloak with the dev realm (keycloak_world.py).

Sign-in and provisioning per test user, roles in the session, logout, and the refusal of a
person with no organization. Isolation between tenants: test_auth_keycloak_isolation.py; the
realm's own rules: test_auth_keycloak_realm.py.
"""

import pytest

from tests.integration.keycloak_browser import KeycloakBrowser
from tests.integration.keycloak_world import (
    CONSOLE,
    DEMO,
    OTHER,
    Session,
    seeded,
    session,
    users_in,
    valkey,
)
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.integration

__all__ = ["seeded", "session", "valkey"]  # the fixtures, re-used


@pytest.mark.parametrize(
    ("email", "tenant", "user_type", "locale", "name"),
    [
        ("admin@demo.test", "Demo Company", "technician", "en", "Amal Admin"),
        ("tech@demo.test", "Demo Company", "technician", "en", "Tariq Technician"),
        ("user@demo.test", "Demo Company", "requester", "ar", "Yusra Requester"),
        ("other@other.test", "Other Company", "technician", "en", "Omar Other"),
    ],
)
async def test_each_test_user_logs_in_and_is_provisioned(
    session: Session,
    seeded: ThrowawayDatabase,
    email: str,
    tenant: str,
    user_type: str,
    locale: str,
    name: str,
) -> None:
    if user_type == "requester":
        # D-129: requester-only people are sent from the console to the portal, with no session.
        sent = await session.login(email)
        assert sent.status_code == 303, sent.text
        callback = await session.login(email, app="portal")
        assert callback.status_code == 302, callback.text
        assert callback.headers["location"].endswith("/home")
    else:
        callback = await session.login(email)
        assert callback.status_code == 302, callback.text
        assert callback.headers["location"] == f"{CONSOLE}/home"
    me = (await session.me()).json()
    assert me["tenant"]["name"] == tenant
    assert me["user"]["display_name"] == name
    assert me["user"]["user_type"] == user_type
    assert me["user"]["locale"] == locale
    (row,) = await users_in(seeded, email, DEMO if tenant == "Demo Company" else OTHER)
    assert (row["display_name"], row["locale"], row["user_type"]) == (name, locale, user_type)


async def test_admin_role_is_carried_into_the_session(session: Session) -> None:
    await session.login("admin@demo.test")
    assert set((await session.me()).json()["user"]["roles"]) == {"tenant_admin", "technician"}


async def test_logout_ends_the_bff_and_keycloak_sessions(session: Session) -> None:
    await session.login("tech@demo.test")
    # While logged in, Keycloak has an SSO session: a new authorization skips the login form.
    sso = session.browser.open((await session.client.get("/api/v1/auth/login")).headers["location"])
    assert sso.status_code == 302
    await session.login("tech@demo.test")
    token = (await session.me()).json()["csrf_token"]
    assert (
        await session.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token})
    ).status_code == 204
    assert (await session.me()).status_code == 401
    after = session.browser.open(
        (await session.client.get("/api/v1/auth/login")).headers["location"]
    )
    assert KeycloakBrowser.shows_login_form(after), "Keycloak session survived the logout"


async def test_user_without_organization_gets_403(session: Session) -> None:
    response = await session.login("nobody@nowhere.test")
    assert response.status_code == 403
    assert response.json()["code"] == "no_organization"
    assert (await session.me()).status_code == 401
    retry = session.browser.open(
        (await session.client.get("/api/v1/auth/login")).headers["location"]
    )
    assert KeycloakBrowser.shows_login_form(retry), "Keycloak session should have been ended"
