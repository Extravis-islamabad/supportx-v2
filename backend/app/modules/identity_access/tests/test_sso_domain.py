"""Single sign-on rules, pure (WP-039, domain/sso.py) and the fetcher's address rule."""

import pytest

from app.modules.identity_access.domain import sso
from app.modules.identity_access.infra.fetch import blocked, rejected


def test_domains_are_cleaned_and_public_or_malformed_ones_refused() -> None:
    found, problems = sso.normalise_domains([" @Acme.TEST. ", "acme.test", "sub.acme.test"])
    assert (found, problems) == (["acme.test", "sub.acme.test"], [])
    _, problems = sso.normalise_domains(["gmail.com", "not a domain", "localhost"])
    assert [p.code for p in problems] == [
        "sso_domain_public",
        "sso_domain_invalid",
        "sso_domain_invalid",
    ]
    assert sso.normalise_domains([])[1][0].code == "sso_domain_required"


@pytest.mark.parametrize(
    ("state", "enabled", "hidden"),
    [("draft", True, True), ("tested", True, True), ("on", True, False), ("off", False, True)],
)
def test_the_keycloak_provider_is_hidden_until_on_and_disabled_when_off(
    state: sso.State, *, enabled: bool, hidden: bool
) -> None:
    found = sso.representation(
        alias="sx-a-1", protocol="oidc", display_name="Acme", config={}, state=state
    )
    assert (found["enabled"], found["hideOnLogin"]) == (enabled, hidden)
    assert "clientSecret" not in found["config"]  # only sent when given


def test_oidc_settings_come_from_discovery() -> None:
    config = sso.oidc_config(
        {
            "issuer": "https://idp.test",
            "authorization_endpoint": "https://idp.test/a",
            "token_endpoint": "https://idp.test/t",
            "jwks_uri": "https://idp.test/k",
        },
        client_id="c",
        scopes="",
    )
    assert config["defaultScope"] == sso.DEFAULT_SCOPES
    assert (config["pkceEnabled"], config["validateSignature"]) == ("true", "true")
    assert not [key for key in config if key.startswith("kc.org.")]  # gone in Keycloak 26.8
    assert sso.issuer_matches("https://idp.test/", "https://idp.test")
    assert not sso.issuer_matches("https://idp.test", "https://evil.test")


def test_saml_assertions_must_be_signed_and_name_the_person() -> None:
    config = sso.saml_config({"singleSignOnServiceUrl": "https://idp/s"})
    assert config["validateSignature"] == "true"
    assert config["nameIDPolicyFormat"] == sso.EMAIL_NAME_ID


def test_domains_are_routed_to_the_set_up_and_others_left_alone() -> None:
    current = [
        {"name": "tenant.test", "verified": True, "autoRedirect": False},
        {
            "name": "old.test",
            "verified": False,
            "identityProviderAlias": "sx-a",
            "autoRedirect": True,
        },
        {
            "name": "theirs.test",
            "verified": False,
            "identityProviderAlias": "sx-b",
            "autoRedirect": True,
        },
    ]
    found = sso.route_domains(
        current, alias="sx-a", mine=["acme.test", "tenant.test"], drop=set(), redirect=True
    )
    by_name = {d["name"]: d for d in found}
    assert by_name["acme.test"] == {
        "name": "acme.test",
        "verified": False,
        "identityProviderAlias": "sx-a",
        "autoRedirect": True,
    }
    assert by_name["tenant.test"]["verified"] is True  # kept, now routed
    assert "identityProviderAlias" not in by_name["old.test"]  # no longer the set-up's: unrouted
    assert by_name["old.test"]["autoRedirect"] is False
    assert by_name["theirs.test"] == current[2]  # another set-up's, untouched
    assert [
        d["name"]
        for d in sso.route_domains(found, alias="sx-a", mine=[], drop={"acme.test"}, redirect=False)
    ] == ["tenant.test", "old.test", "theirs.test"]


def test_only_mapped_fields_get_a_mapper() -> None:
    mapping = sso.Mapping("mail", "given", "family", department="dept")
    found = sso.mappers("saml", mapping)
    targets = {m["config"]["user.attribute"]: m["config"]["attribute.name"] for m in found}
    assert targets == {
        "email": "mail",
        "firstName": "given",
        "lastName": "family",
        sso.DEPARTMENT_ATTRIBUTE: "dept",
    }
    assert all(m["identityProviderMapper"] == "saml-user-attribute-idp-mapper" for m in found)


def test_urls_and_addresses_a_check_may_contact() -> None:
    assert sso.check_url("ftp://idp.test", "issuer") is not None
    assert sso.check_url("https://user:pw@idp.test", "issuer") is not None
    assert sso.check_url("https://idp.test/x", "issuer") is None
    assert blocked("169.254.169.254", allow_loopback=True)  # cloud metadata, never
    assert blocked("127.0.0.1", allow_loopback=False)
    assert not blocked("127.0.0.1", allow_loopback=True)
    assert not blocked("10.1.2.3", allow_loopback=False)  # on-prem providers live there


@pytest.mark.parametrize(
    ("status", "body", "wrong"),
    [
        (401, {"error": "invalid_client"}, True),  # Entra ID, Okta, Google
        (
            401,
            {
                "error": "unauthorized_client",
                "error_description": "Invalid client or Invalid client credentials",
            },
            True,
        ),  # Keycloak, wrong secret
        (
            401,
            {
                "error": "unauthorized_client",
                "error_description": "Client not enabled to retrieve service account",
            },
            False,
        ),  # Keycloak, right secret
        (400, {"error": "unsupported_grant_type"}, False),
        (400, {"error": "invalid_scope"}, False),
        (401, {}, True),
    ],
)
def test_a_wrong_client_secret_is_told_apart_from_a_refused_grant(
    status: int, body: dict[str, object], *, wrong: bool
) -> None:
    assert rejected(status, body) is wrong
