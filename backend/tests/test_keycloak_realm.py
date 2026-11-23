"""The production realm never carries demo users or organizations (WP-014)."""

import json

from tooling.keycloak_realm import BASE_REALM, DEV_REALM, base_realm, render


def test_base_realm_is_the_dev_realm_without_demo_data() -> None:
    dev = json.loads(DEV_REALM.read_text(encoding="utf-8"))
    base = json.loads(BASE_REALM.read_text(encoding="utf-8"))
    assert "users" in dev
    assert "organizations" in dev
    assert "users" not in base
    assert "organizations" not in base
    # The same clients, but the password grant (dev quick sign-in, D-151) only in the dev file.
    without_grant = [
        {**c, "directAccessGrantsEnabled": False} if "directAccessGrantsEnabled" in c else c
        for c in dev["clients"]
    ]
    assert base["clients"] == without_grant
    assert base["passwordPolicy"] == dev["passwordPolicy"]
    # Committed file is current (make keycloak-realm regenerates it).
    assert BASE_REALM.read_text(encoding="utf-8") == render(base_realm(dev))


def test_no_hard_coded_ui_origins_in_either_realm() -> None:
    for path in (DEV_REALM, BASE_REALM):
        text = path.read_text(encoding="utf-8")
        assert "localhost" not in text
        assert "${SUPPORTX_KC_CONSOLE_ORIGIN}/api/v1/auth/callback" in text
        assert "${SUPPORTX_KC_PORTAL_ORIGIN}/api/v1/auth/callback" in text


def test_the_production_realm_never_allows_the_password_grant() -> None:
    """D-151: the base realm forbids it on every client, and keeps its own session limits."""
    base = json.loads(BASE_REALM.read_text(encoding="utf-8"))
    assert all(c.get("directAccessGrantsEnabled") is not True for c in base["clients"])
    assert (base["rememberMe"], base["ssoSessionIdleTimeout"], base["ssoSessionMaxLifespan"]) == (
        False,
        1800,
        43200,
    )
    assert "ssoSessionIdleTimeoutRememberMe" not in base


def test_both_realms_rotate_refresh_tokens() -> None:
    """Audit row 26: every refresh token works once; the BFF stores each new one."""
    for path in (BASE_REALM, DEV_REALM):
        realm = json.loads(path.read_text(encoding="utf-8"))
        assert (realm["revokeRefreshToken"], realm["refreshTokenMaxReuse"]) == (True, 0), path


def test_the_dev_realm_has_the_quick_sign_in_settings() -> None:
    dev = json.loads(DEV_REALM.read_text(encoding="utf-8"))
    week = 7 * 86400
    assert (dev["rememberMe"], dev["ssoSessionIdleTimeout"], dev["ssoSessionMaxLifespan"]) == (
        True,
        week,
        week,
    )
    granted = {c["clientId"] for c in dev["clients"] if c.get("directAccessGrantsEnabled")}
    assert granted == {"supportx-console", "supportx-portal"}
