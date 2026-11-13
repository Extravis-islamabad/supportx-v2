"""The approximate sign-in place (WP-057 S2b, D-170): mapped site, internal, then GeoIP."""

import ipaddress
import uuid

import pytest

from app.modules.identity_access.domain.place import (
    GeoHit,
    IpAddress,
    Place,
    SiteNetwork,
    is_internal,
    mapped_site,
    parse_address,
    parse_network,
    place_of,
)

HQ = uuid.UUID("00000000-0000-7000-8000-000000000001")
LAB = uuid.UUID("00000000-0000-7000-8000-000000000002")
OFFICE_EGRESS = uuid.UUID("00000000-0000-7000-8000-000000000003")
NETWORKS = (
    SiteNetwork(parse_network("10.1.0.0/16"), HQ),
    SiteNetwork(parse_network("10.1.7.0/24"), LAB),  # more specific: wins inside the /16
    SiteNetwork(parse_network("203.0.113.8/29"), OFFICE_EGRESS),  # a public range, mapped too
    SiteNetwork(parse_network("2001:db8:1::/48"), HQ),
)
LAHORE = GeoHit(city="Lahore", country="pk")
asked: list[IpAddress] = []


def lookup(address: IpAddress) -> GeoHit | None:
    asked.append(address)
    return LAHORE if str(address) == "8.8.8.8" else None


@pytest.fixture(autouse=True)
def _clear() -> None:
    asked.clear()


def test_a_mapped_network_names_its_site_the_most_specific_prefix_winning() -> None:
    assert place_of("10.1.2.3", NETWORKS, lookup) == Place("site", site_id=HQ)
    assert place_of("10.1.7.9", NETWORKS, lookup) == Place("site", site_id=LAB)
    assert place_of("203.0.113.12", NETWORKS, lookup) == Place("site", site_id=OFFICE_EGRESS)
    assert place_of("2001:db8:1:5::1", NETWORKS, lookup) == Place("site", site_id=HQ)
    assert asked == []  # the database is never asked for a mapped address


@pytest.mark.parametrize(
    "address",
    [
        "10.9.9.9",  # RFC 1918, not mapped
        "172.16.4.1",
        "192.168.1.10",
        "127.0.0.1",  # loopback
        "169.254.10.1",  # link-local
        "100.64.3.2",  # carrier-grade NAT (RFC 6598)
        "fd12:3456::1",  # IPv6 unique-local
        "fe80::1",  # IPv6 link-local
        "::1",
        "::ffff:192.168.0.5",  # IPv4-mapped IPv6
    ],
)
def test_an_internal_address_is_the_internal_network_never_a_guessed_city(address: str) -> None:
    assert place_of(address, NETWORKS, lookup) == Place("internal")
    assert asked == []


def test_a_public_address_gets_the_databases_city_and_country() -> None:
    assert place_of("8.8.8.8", NETWORKS, lookup) == Place("geo", city="Lahore", country="PK")


@pytest.mark.parametrize("value", [None, "", "not-an-ip", "10.1.2.3:443", "1.1.1.1"])
def test_no_place_when_the_address_or_the_database_says_nothing(value: str | None) -> None:
    assert place_of(value, NETWORKS, lookup) is None


def test_ipv4_mapped_addresses_are_read_as_ipv4() -> None:
    assert parse_address("::ffff:10.1.2.3") == ipaddress.ip_address("10.1.2.3")
    assert place_of("::ffff:10.1.2.3", NETWORKS, lookup) == Place("site", site_id=HQ)


def test_a_range_must_be_written_with_its_host_bits_clear() -> None:
    assert str(parse_network("10.1.0.0/16")) == "10.1.0.0/16"
    assert str(parse_network("192.0.2.7")) == "192.0.2.7/32"
    for bad in ("10.1.2.3/16", "10.1.0.0/33", "nonsense", "2001:db8::1/32"):
        with pytest.raises(ValueError, match=r".+"):
            parse_network(bad)


def test_no_match_across_ip_versions() -> None:
    v6_only = (SiteNetwork(parse_network("::/0"), HQ),)
    assert mapped_site(ipaddress.ip_address("8.8.8.8"), v6_only) is None


def test_carrier_grade_nat_and_documentation_ranges_are_internal() -> None:
    for address in ("100.64.0.1", "100.127.255.254", "192.0.2.1", "198.51.100.20", "2001:db8::1"):
        assert is_internal(ipaddress.ip_address(address)), address
    assert not is_internal(ipaddress.ip_address("8.8.8.8"))
    assert not is_internal(ipaddress.ip_address("2a00:1450:4001::1"))


def test_the_stored_form_round_trips_and_damaged_forms_read_as_none() -> None:
    for place in (
        Place("site", site_id=HQ),
        Place("internal"),
        Place("geo", city="Lahore", country="PK"),
        Place("geo", country="PK"),
    ):
        assert Place.from_dict(place.to_dict()) == place
    for damaged in (
        None,
        "x",
        {},
        {"kind": "moon"},
        {"kind": "site"},
        {"kind": "site", "site_id": "x"},
    ):
        assert Place.from_dict(damaged) is None
    # A city is tidied and capped; a country is only ever two letters.
    tidy = Place.from_dict({"kind": "geo", "city": "  New \n York  ", "country": "usa"})
    assert tidy == Place("geo", city="New York", country=None)
