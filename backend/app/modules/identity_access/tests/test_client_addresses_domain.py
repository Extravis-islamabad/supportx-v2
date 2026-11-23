"""Which tenant addresses the sign-in clients accept (ADR-031, plan A). Pure."""

import pytest

from app.modules.identity_access.domain.client_addresses import (
    CALLBACK_PATH,
    Addresses,
    ClientBase,
    change,
    managed_host,
    normalise_host,
    tenant_hosts,
    wanted,
)

CONSOLE = ClientBase("supportx-console", "https://support.example.com")
DEV = ClientBase("supportx-console", "http://localhost:5173")
PORTAL_PATH = ClientBase("supportx-portal", "https://support.example.com/portal")


def test_a_tenant_has_its_subdomain_and_its_verified_domains() -> None:
    hosts = tenant_hosts("acme", "support.example.com", ["help.acme.com"])
    assert hosts == {"acme.support.example.com", "help.acme.com"}


def test_without_a_base_domain_only_verified_domains_count() -> None:
    assert tenant_hosts("acme", None, ["help.acme.com"]) == {"help.acme.com"}
    assert tenant_hosts("acme", None, []) == frozenset()


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("Help.ACME.com", "help.acme.com"),
        ("help.acme.com.", "help.acme.com"),
        ("bücher.example", "xn--bcher-kva.example"),
        ("help.acme.com:443", None),
        ("help.acme.com/x", None),
        ("10.0.0.1", None),
        ("localhost", None),
        ("a..b", None),
        ("", None),
    ],
)
def test_hosts_are_normalised_as_keycloak_compares_them(given: str, expected: str | None) -> None:
    assert normalise_host(given) == expected


def test_the_callback_keeps_the_clients_scheme_and_port_and_never_the_shared_host() -> None:
    found = wanted(DEV, {"demo.localhost", "localhost"})
    assert found.redirect_uris == {f"http://demo.localhost:5173{CALLBACK_PATH}"}
    assert found.web_origins == {"http://demo.localhost:5173"}
    # A portal under a path keeps its callback at the host's /api (as AuthService.origin).
    portal = wanted(PORTAL_PATH, {"help.acme.com"})
    assert portal.redirect_uris == {f"https://help.acme.com{CALLBACK_PATH}"}


def test_only_entries_of_supportx_shape_are_managed() -> None:
    assert managed_host(CONSOLE, f"https://help.acme.com{CALLBACK_PATH}") == "help.acme.com"
    assert managed_host(CONSOLE, "https://help.acme.com") == "help.acme.com"
    for operators in (
        "https://support.example.com/api/v1/auth/callback",  # the shared host
        "https://help.acme.com/*",  # a wildcard
        "http://help.acme.com/api/v1/auth/callback",  # another scheme
        "https://help.acme.com:8443/api/v1/auth/callback",  # another port
        "https://help.acme.com/other",  # another path
        "https://help.acme.com/api/v1/auth/callback/",  # not the exact shape
        "+",  # Keycloak's "same as redirect URIs" origin
    ):
        assert managed_host(CONSOLE, operators) is None, operators


def test_a_verified_domain_is_added_and_nothing_is_removed() -> None:
    want = wanted(CONSOLE, {"help.acme.com"})
    found = change(CONSOLE, Addresses(), want)
    assert found.add == want
    assert not found.remove


def test_the_same_state_twice_changes_nothing() -> None:
    want = wanted(CONSOLE, {"help.acme.com"})
    assert not change(CONSOLE, want, want)


def test_a_removed_domain_goes_only_when_the_event_names_it() -> None:
    current = wanted(CONSOLE, {"help.acme.com", "other.example"})
    want = wanted(CONSOLE, {"other.example"})
    named = change(CONSOLE, current, want, removable=frozenset({"help.acme.com"}))
    assert named.remove == wanted(CONSOLE, {"help.acme.com"})
    # An event for one domain never takes another tenant's address away.
    other = change(CONSOLE, current, wanted(CONSOLE, set()), removable=frozenset({"x.example"}))
    assert not other.remove


def test_the_reconcile_removes_a_managed_stray_and_keeps_an_operators_entry() -> None:
    operators = {"https://help.acme.com/*", "https://support.example.com/api/v1/auth/callback"}
    current = Addresses(
        redirect_uris=frozenset({f"https://gone.example{CALLBACK_PATH}", *operators}),
        web_origins=frozenset({"https://gone.example", "+"}),
    )
    found = change(CONSOLE, current, wanted(CONSOLE, set()))
    assert found.remove.redirect_uris == {f"https://gone.example{CALLBACK_PATH}"}
    assert found.remove.web_origins == {"https://gone.example"}
