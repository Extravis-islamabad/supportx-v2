"""The Keycloak events import's pure rules (WP-057 S1b)."""

from dataclasses import replace

from app.modules.identity_access.domain.sign_in import SignInApp, SignInMethod
from app.modules.identity_access.domain.sign_in_import import (
    KeycloakEvent,
    app_of,
    clean_ip,
    method_of,
    redirect_host,
    slug_of_alias,
    usable,
)

WRONG_PASSWORD = KeycloakEvent(
    id="e1",
    type="LOGIN_ERROR",
    time_ms=1,
    client_id="supportx-console",
    error="invalid_user_credentials",
    user_id=None,
    ip="192.0.2.1",
    identity_provider=None,
    redirect_uri=None,
)


def test_an_alias_names_its_tenant_slug_even_with_hyphens() -> None:
    assert slug_of_alias("sx-acme-1a2b3c") == "acme"
    assert slug_of_alias("sx-north-west-ltd-1a2b3c") == "north-west-ltd"
    assert slug_of_alias("google") is None
    assert slug_of_alias("sx-") is None
    assert slug_of_alias(None) is None


def test_only_the_console_and_portal_are_a_persons_sign_in() -> None:
    assert app_of(WRONG_PASSWORD) is SignInApp.CONSOLE
    assert app_of(replace(WRONG_PASSWORD, client_id="supportx-portal")) is SignInApp.PORTAL
    assert app_of(replace(WRONG_PASSWORD, client_id="supportx-identity")) is None
    assert app_of(replace(WRONG_PASSWORD, client_id=None)) is None


def test_an_identity_provider_makes_it_single_sign_on() -> None:
    assert method_of(WRONG_PASSWORD) is SignInMethod.PASSWORD
    brokered = replace(WRONG_PASSWORD, identity_provider="sx-acme-1a2b3c")
    assert method_of(brokered) is SignInMethod.SINGLE_SIGN_ON


def test_host_address_and_id_are_checked() -> None:
    assert redirect_host("https://Acme.Example.com:8443/api/v1/auth/callback") == "acme.example.com"
    assert redirect_host("not a url") is None
    assert redirect_host("http://[::1") is None
    assert clean_ip("2001:db8::1") == "2001:db8::1"
    assert clean_ip("unknown") is None
    assert usable(WRONG_PASSWORD) is True
    assert usable(replace(WRONG_PASSWORD, id="")) is False
    assert usable(replace(WRONG_PASSWORD, id="x" * 65)) is False
