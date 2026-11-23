"""Which addresses outbound calls may reach (ADR-043 §8; lane B's constraints). Pure: no I/O.

A tenant types the address (a webhook, a workflow's call), so every call is a server-side
request forgery risk. Never contacted: loopback and link-local (cloud metadata), private ranges,
CGNAT (100.64/10), 0/8, multicast, broadcast and reserved space. Link-local, multicast and
unspecified addresses stay closed whatever the configuration says. IPv6 forms that carry an IPv4
address (mapped, 6to4, Teredo, NAT64) are judged as that IPv4 address. Only the installation's
configuration may open a private range or host, never a tenant.
"""

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass, field

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

DEFAULT_PORTS = frozenset({80, 443})
MIN_PREFIX_V4 = 8  # no allow-list entry wider than this: it would open every private range
MIN_PREFIX_V6 = 16
_LOOPBACK: dict[int, IPNetwork] = {
    4: ipaddress.ip_network("127.0.0.0/8"),
    6: ipaddress.ip_network("::1/128"),
}


class AllowanceError(ValueError):
    """An installation allow-list entry that is refused (too wide, or loopback outside dev)."""


_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_THIS_NETWORK = ipaddress.ip_network("0.0.0.0/8")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")


@dataclass(frozen=True)
class Allowance:
    """What the installation opens beyond the public internet (configuration only)."""

    networks: tuple[IPNetwork, ...] = ()
    hosts: frozenset[str] = frozenset()  # lower-case names whose addresses may be private
    # The ports a call may use; None = any port (identity providers often listen on 8443: the
    # address rules still apply, which is what keeps a call off internal services).
    ports: frozenset[int] | None = field(default=DEFAULT_PORTS)

    def any_port(self) -> "Allowance":
        """The same networks and hosts, on any port."""
        return Allowance(self.networks, self.hosts, None)

    @classmethod
    def from_config(
        cls,
        entries: Iterable[str],
        extra_ports: Iterable[int] = (),
        *,
        allow_loopback: bool = False,
    ) -> "Allowance":
        """CIDRs and host names from the installation's settings (lane B's hygiene rules).

        Raises AllowanceError for a range wider than /8 (IPv4) or /16 (IPv6), which would open
        every private range, and for one holding loopback unless `allow_loopback` (dev and test
        profiles only). Host names are taken as given.
        """
        networks: list[IPNetwork] = []
        hosts: set[str] = set()
        for raw in entries:
            entry = raw.strip()
            if not entry:
                continue
            try:
                network = ipaddress.ip_network(entry, strict=False)
            except ValueError:
                hosts.add(entry.lower().rstrip("."))
                continue
            widest = MIN_PREFIX_V4 if network.version == 4 else MIN_PREFIX_V6  # noqa: PLR2004
            if network.prefixlen < widest:
                raise AllowanceError(entry)
            if network.overlaps(_LOOPBACK[network.version]) and not allow_loopback:
                raise AllowanceError(entry)
            networks.append(network)
        return cls(tuple(networks), frozenset(hosts), DEFAULT_PORTS | frozenset(extra_ports))


def embedded_ipv4(ip: IPAddress) -> ipaddress.IPv4Address | None:
    """The IPv4 address an IPv6 address carries (mapped, 6to4, Teredo, NAT64), or None."""
    if not isinstance(ip, ipaddress.IPv6Address):
        return None
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]  # the client's address
    if ip in _NAT64 or ip in _NAT64_LOCAL:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def _never(ip: IPAddress) -> bool:
    """Addresses no configuration opens: link-local (cloud metadata), multicast, unspecified.

    Loopback is private: only an installation that lists it (dev and CI receivers) reaches it.
    """
    return ip.is_link_local or ip.is_multicast or ip.is_unspecified


def _private(ip: IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv4Address) and (ip in _CGNAT or ip in _THIS_NETWORK):
        return True
    if isinstance(ip, ipaddress.IPv4Address) and ip == ipaddress.IPv4Address("255.255.255.255"):
        return True
    return ip.is_private or ip.is_reserved or not ip.is_global


def allowed(ip: IPAddress, host: str, allowance: Allowance) -> bool:
    """Whether a call to `host` may connect to `ip`."""
    inner = embedded_ipv4(ip)
    if inner is not None:
        return allowed(inner, host, allowance)
    if _never(ip):
        return False
    if not _private(ip):
        return True
    if host.lower().rstrip(".") in allowance.hosts:
        return True
    return any(ip.version == net.version and ip in net for net in allowance.networks)
