"""Single sign-on rules, pure (WP-039, domain/sso.py) and the fetcher's address rule."""

import ipaddress
from urllib.parse import urlsplit

import httpcore
import pytest

from app.modules.identity_access.domain import sso
from app.modules.identity_access.infra.fetch import BLOCKED, FetchError, fetch_document, rejected
from app.shared.egress import Allowance
from app.shared.egress.addresses import IPAddress


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


PUBLIC_ONLY = Allowance()  # no list: the public internet only
LISTED = Allowance.from_config(["10.1.0.0/16", "idp.corp.internal"])
DEV = Allowance.from_config(["127.0.0.0/8"], allow_loopback=True)


async def _blocked(url: str, allowance: Allowance, *answers: str) -> bool:
    """Whether the fetch is refused on its address, before any connection (audit #3)."""

    async def resolver(host: str, port: int) -> list[IPAddress]:
        del host, port
        return [ipaddress.ip_address(a) for a in answers]

    try:
        await fetch_document(url, allowance=allowance, resolver=resolver)
    except FetchError as error:
        return error.code == BLOCKED
    return False


@pytest.mark.parametrize(
    ("url", "allowance", "answers", "refused"),
    [
        ("https://169.254.169.254/latest", LISTED, (), True),  # cloud metadata, never
        ("https://[fe80::1]/x", LISTED, (), True),  # link-local IPv6, never
        ("https://10.1.2.3/x", PUBLIC_ONLY, (), True),  # private: only the installation opens it
        ("https://172.16.0.9:8443/x", PUBLIC_ONLY, (), True),
        ("https://100.64.0.1/x", PUBLIC_ONLY, (), True),  # CGNAT
        ("https://127.0.0.1/x", PUBLIC_ONLY, (), True),  # loopback
        ("https://[::ffff:10.1.2.3]/x", PUBLIC_ONLY, (), True),  # an IPv4-mapped private address
        ("https://idp.example.com/x", PUBLIC_ONLY, ("10.1.2.3",), True),  # a name to a private one
        ("https://idp.example.com/x", PUBLIC_ONLY, ("93.184.216.34", "10.9.9.9"), True),  # any bad
        ("https://idp.example.com/x", LISTED, ("169.254.169.254",), True),
    ],
)
async def test_a_set_up_check_never_reaches_private_or_metadata_addresses(
    url: str, allowance: Allowance, answers: tuple[str, ...], *, refused: bool
) -> None:
    assert await _blocked(url, allowance, *answers) is refused


@pytest.mark.parametrize(
    ("url", "allowance", "answers"),
    [
        ("https://10.1.2.3:8443/x", LISTED, ()),  # a listed on-prem provider, on any port
        ("https://idp.corp.internal/x", LISTED, ("192.168.4.4",)),  # a listed host name
        ("http://127.0.0.1:8080/x", DEV, ()),  # dev and test: the local provider
    ],
)
async def test_the_installation_may_open_its_own_providers(
    url: str, allowance: Allowance, answers: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    connected: list[tuple[str, int]] = []

    async def connect_tcp(self: object, host: str, port: int, **kwargs: object) -> None:
        del self, kwargs
        connected.append((host, port))
        raise httpcore.ConnectError(host)  # no real network in a unit test

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect_tcp)
    assert await _blocked(url, allowance, *answers) is False
    assert len(connected) == 1  # the checked address, once (pinned: never resolved again)
    assert connected[0][0] == (answers[0] if answers else urlsplit(url).hostname)


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
