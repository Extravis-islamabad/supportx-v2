"""IP allow-lists, pure (REQ-SEC-034; domain/network.py)."""

import ipaddress

import pytest

from app.modules.identity_access.domain.network import (
    IP_ALLOW_MAX,
    ListProblem,
    NetworkApp,
    address_of,
    allows,
    locks_out,
    parse_list,
)


def test_a_list_is_normalised_deduplicated_and_kept_in_order() -> None:
    parsed = parse_list([" 10.1.0.0/16 ", "192.0.2.7", "", "2001:db8::/32", "10.1.0.0/16"])
    assert parsed.problem is None
    assert [str(n) for n in parsed.networks] == ["10.1.0.0/16", "192.0.2.7/32", "2001:db8::/32"]


@pytest.mark.parametrize(
    ("entry", "problem"),
    [
        ("not-an-address", ListProblem.INVALID),
        ("10.1.2.3/16", ListProblem.INVALID),  # host bits under the mask: a typing mistake
        ("10.0.0.0/33", ListProblem.INVALID),
        ("0.0.0.0/0", ListProblem.EVERYTHING),  # "everyone" is an empty list
        ("::/0", ListProblem.EVERYTHING),
    ],
)
def test_a_wrong_entry_is_refused_with_its_reason(entry: str, problem: ListProblem) -> None:
    parsed = parse_list(["192.0.2.0/24", entry])
    assert (parsed.problem, parsed.bad_entry) == (problem, entry)
    assert parsed.networks == ()


def test_a_list_is_capped() -> None:
    entries = [f"10.0.{i}.0/24" for i in range(IP_ALLOW_MAX + 1)]
    assert parse_list(entries).problem is ListProblem.TOO_MANY
    assert parse_list(entries[:IP_ALLOW_MAX]).problem is None


def test_an_empty_list_lets_everyone_in_and_a_list_only_its_ranges() -> None:
    office = parse_list(["10.1.0.0/16", "2001:db8::/32"]).networks
    assert allows((), address_of("203.0.113.9"))
    assert allows(office, address_of("10.1.200.4"))
    assert allows(office, address_of("2001:db8::1"))
    assert not allows(office, address_of("10.2.0.1"))
    # An IPv4 address that arrives as IPv6 from a dual-stack proxy is judged as IPv4.
    assert allows(office, address_of("::ffff:10.1.0.5"))
    # An address the list cannot read is refused: a restriction never waves it through.
    assert not allows(office, address_of("unknown"))
    assert not allows(office, None)


def test_saving_a_list_that_shuts_out_the_admin_is_refused() -> None:
    office = parse_list(["10.1.0.0/16"]).networks
    here = address_of("10.1.0.20")
    away = address_of("198.51.100.4")
    assert locks_out({NetworkApp.CONSOLE: office}, here, via_api_key=False) is None
    assert locks_out({NetworkApp.CONSOLE: office}, away, via_api_key=False) is NetworkApp.CONSOLE
    # The API list counts only when the admin saves through an API key.
    lists = {NetworkApp.CONSOLE: (), NetworkApp.API: office}
    assert locks_out(lists, away, via_api_key=False) is None
    assert locks_out(lists, away, via_api_key=True) is NetworkApp.API
    # The portal list never locks the admin out of the console.
    assert locks_out({NetworkApp.PORTAL: office}, away, via_api_key=False) is None
    assert ipaddress.ip_address("10.1.0.20") == here
