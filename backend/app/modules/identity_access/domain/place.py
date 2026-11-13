"""Where a sign-in came from, approximately (REQ-SEC-030, REQ-SEC-033; WP-057 S2b; D-170).

Pure: no I/O. The order is fixed:
1. **An admin-mapped network** (`site_networks`): the most specific prefix holding the address
   names a site ("Islamabad HQ"). It works for internal and public ranges alike: an office's own
   public address can be mapped too.
2. **An internal address** (RFC 1918, loopback, link-local, IPv6 unique-local, carrier-grade NAT,
   and the like): "Internal network", never a guessed city (D-170).
3. **The GeoIP database** (DB-IP Lite, `infra/geoip.py`): a city and a country, approximate.
4. Otherwise no place. A missing database is not an error: the place is only ever shown as help.

The place keeps a site's ID, never its name, so a renamed site shows its new name; the city is
the database's English name and the country its ISO 3166 code (the UI names it in the person's
language).
"""

import ipaddress
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
PlaceKind = Literal["site", "internal", "geo"]

MAX_SITE_NETWORKS = 200
_CITY_MAX = 120

# Never on the internet: shown as "Internal network". Python's `is_private` covers most of it
# (documentation ranges included); carrier-grade NAT (100.64.0.0/10, RFC 6598) is listed as well,
# since Python versions disagree on whether it is "private", and it is never a place either way.
_INTERNAL: tuple[IpNetwork, ...] = (ipaddress.ip_network("100.64.0.0/10"),)


@dataclass(frozen=True)
class SiteNetwork:
    """An admin's mapping of an address range to a site."""

    network: IpNetwork
    site_id: uuid.UUID


@dataclass(frozen=True)
class GeoHit:
    """What the GeoIP database knows about an address."""

    city: str | None
    country: str | None  # ISO 3166-1 alpha-2, upper case


@dataclass(frozen=True)
class Place:
    """An approximate place: a mapped site, the internal network, or a city and country."""

    kind: PlaceKind
    site_id: uuid.UUID | None = None
    city: str | None = None
    country: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """The stored form (JSONB on the sign-in log, a dict in the session record)."""
        data: dict[str, Any] = {"kind": self.kind}
        if self.site_id is not None:
            data["site_id"] = str(self.site_id)
        if self.city is not None:
            data["city"] = self.city
        if self.country is not None:
            data["country"] = self.country
        return data

    @classmethod
    def from_dict(cls, data: object) -> "Place | None":
        """The stored form back; None for anything malformed (an older or a damaged record)."""
        if not isinstance(data, dict):
            return None
        kind = data.get("kind")
        try:
            if kind == "site":
                return cls("site", site_id=uuid.UUID(str(data["site_id"])))
            if kind == "internal":
                return cls("internal")
            if kind == "geo":
                return cls(
                    "geo", city=_text(data.get("city")), country=_country(data.get("country"))
                )
        except (KeyError, ValueError):
            return None
        return None


def parse_address(value: str | None) -> IpAddress | None:
    """An address the BFF saw, or None (empty, malformed, or with a zone that is not ours)."""
    if not value:
        return None
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped  # ::ffff:10.1.2.3 is 10.1.2.3
    return address


def is_internal(address: IpAddress) -> bool:
    """Whether an address is never on the internet (D-170: "Internal network")."""
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
        or address.is_multicast
        or any(address in network for network in _INTERNAL)
    )


def mapped_site(address: IpAddress, networks: Sequence[SiteNetwork]) -> uuid.UUID | None:
    """The site of the most specific mapped prefix holding the address (ties: the first listed)."""
    best: SiteNetwork | None = None
    for entry in networks:
        if address.version != entry.network.version or address not in entry.network:
            continue
        if best is None or entry.network.prefixlen > best.network.prefixlen:
            best = entry
    return None if best is None else best.site_id


def place_of(
    value: str | None,
    networks: Sequence[SiteNetwork],
    lookup: Callable[[IpAddress], GeoHit | None],
) -> Place | None:
    """The sign-in's approximate place, in D-170's order (mapped site, internal, GeoIP)."""
    address = parse_address(value)
    if address is None:
        return None
    site = mapped_site(address, networks)
    if site is not None:
        return Place("site", site_id=site)
    if is_internal(address):
        return Place("internal")
    hit = lookup(address)
    if hit is None or (hit.city is None and hit.country is None):
        return None
    return Place("geo", city=_text(hit.city), country=_country(hit.country))


def parse_network(value: str) -> IpNetwork:
    """An admin's range ("10.1.0.0/16", "2001:db8::/48"); ValueError when it is not one.

    Host bits must be zero ("10.1.2.3/16" is refused, not silently widened), and a single
    address without a prefix is the /32 or /128 it means.
    """
    return ipaddress.ip_network(value.strip(), strict=True)


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:_CITY_MAX] or None


def _country(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    return code if len(code) == 2 and code.isascii() and code.isalpha() else None  # noqa: PLR2004 - ISO 3166-1 alpha-2
