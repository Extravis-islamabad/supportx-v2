"""Single sign-on rules, pure (WP-039, domain/sso.py) and the fetcher's address rule."""

import pytest

from app.modules.identity_access.domain import sso
from app.modules.identity_access.infra.fetch import blocked


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


def test_oidc_settings_come_from_discovery_and_onboard_by_any_tenant_domain() -> None:
    config = sso.oidc_config(
        {
            "issuer": "https://idp.test",
            "authorization_endpoint": "https://idp.test/a",
            "token_endpoint": "https://idp.test/t",
            "jwks_uri": "https://idp.test/k",
        },
        client_id="c",
        scopes="",
        email_redirect=False,
    )
    assert config["defaultScope"] == sso.DEFAULT_SCOPES
    assert (config["kc.org.domain"], config["pkceEnabled"]) == ("ANY", "true")
    assert config["kc.org.broker.redirect.mode.email-matches"] == "false"
    assert sso.issuer_matches("https://idp.test/", "https://idp.test")
    assert not sso.issuer_matches("https://idp.test", "https://evil.test")


def test_saml_assertions_must_be_signed_and_name_the_person() -> None:
    config = sso.saml_config({"singleSignOnServiceUrl": "https://idp/s"}, email_redirect=True)
    assert config["validateSignature"] == "true"
    assert config["nameIDPolicyFormat"] == sso.EMAIL_NAME_ID
    assert config["kc.org.broker.redirect.mode.email-matches"] == "true"


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
