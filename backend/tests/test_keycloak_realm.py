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
    assert base["clients"] == dev["clients"]
    assert base["passwordPolicy"] == dev["passwordPolicy"]
    # Committed file is current (make keycloak-realm regenerates it).
    assert BASE_REALM.read_text(encoding="utf-8") == render(base_realm(dev))


def test_no_hard_coded_ui_origins_in_either_realm() -> None:
    for path in (DEV_REALM, BASE_REALM):
        text = path.read_text(encoding="utf-8")
        assert "localhost" not in text
        assert "${SUPPORTX_KC_CONSOLE_ORIGIN}/api/v1/auth/callback" in text
        assert "${SUPPORTX_KC_PORTAL_ORIGIN}/api/v1/auth/callback" in text
