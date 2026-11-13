"""Who may sign in or call, by address (REQ-SEC-034; WP-057 S1a). Pure: no I/O.

A tenant keeps one allow-list per app: the console, the portal and the API (API keys). An empty
list means no restriction. Entries are CIDR ranges or single addresses, IPv4 or IPv6, at most
IP_ALLOW_MAX per list (lane B's review). An IPv4 address that arrives as IPv6 (::ffff:a.b.c.d,
from a dual-stack proxy) is judged as the IPv4 address it carries.

Saving a list that would shut out the admin saving it is refused (AC2): their own address must
be inside the console list, and inside the API list too when they save through an API key.
"""

import ipaddress
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

IP_ALLOW_MAX = 50

Network = ipaddress.IPv4Network | ipaddress.IPv6Network
Address = ipaddress.IPv4Address | ipaddress.IPv6Address


class NetworkApp(StrEnum):
    """The parts of SupportX a list guards."""

    CONSOLE = "console"
    PORTAL = "portal"
    API = "api"


class ListProblem(StrEnum):
    """Why a list is refused (field error codes; labelled)."""

    INVALID = "ip_allow_invalid"  # not an address or range
    TOO_MANY = "ip_allow_too_many"
    EVERYTHING = "ip_allow_everything"  # 0.0.0.0/0 or ::/0: say "empty" instead
    LOCKS_YOU_OUT = "ip_allow_locks_you_out"


@dataclass(frozen=True)
class Parsed:
    """A list as saved (normalised, duplicates gone, in the order given) or why not."""

    networks: tuple[Network, ...]
    problem: ListProblem | None = None
    bad_entry: str | None = None


def parse_list(entries: Iterable[str]) -> Parsed:
    """Normalise `entries` ("10.1.0.0/16", "192.0.2.7", "2001:db8::/32") into networks.

    A host address becomes its /32 or /128; host bits under a mask are refused rather than
    silently dropped ("10.1.2.3/16" is a typing mistake, not 10.1.0.0/16).
    """
    networks: list[Network] = []
    for raw in entries:
        entry = raw.strip()
        if not entry:
            continue
        try:
            network = ipaddress.ip_network(entry, strict=True)
        except ValueError:
            return Parsed((), ListProblem.INVALID, entry)
        if network.prefixlen == 0:
            return Parsed((), ListProblem.EVERYTHING, entry)
        if network not in networks:
            networks.append(network)
    if len(networks) > IP_ALLOW_MAX:
        return Parsed((), ListProblem.TOO_MANY)
    return Parsed(tuple(networks))


def _plain(address: Address) -> Address:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def address_of(raw: str | None) -> Address | None:
    """The client's address as an address, or None when unknown or unreadable."""
    if raw is None:
        return None
    try:
        return _plain(ipaddress.ip_address(raw.strip().strip("[]")))
    except ValueError:
        return None


def allows(networks: Sequence[Network], address: Address | None) -> bool:
    """Whether `address` may use the app guarded by `networks` (empty: everyone).

    An unknown address is refused by a non-empty list: a restriction that waves through what it
    cannot read restricts nothing.
    """
    if not networks:
        return True
    if address is None:
        return False
    plain = _plain(address)
    return any(plain.version == n.version and plain in n for n in networks)


def locks_out(
    lists: Mapping[NetworkApp, Sequence[Network]], address: Address | None, *, via_api_key: bool
) -> NetworkApp | None:
    """The list that would shut out the admin saving it, or None (AC2).

    The console always (that is where the admin works); the API too when they save with a key.
    """
    checked = (NetworkApp.CONSOLE, NetworkApp.API) if via_api_key else (NetworkApp.CONSOLE,)
    for app in checked:
        if not allows(lists.get(app, ()), address):
            return app
    return None
