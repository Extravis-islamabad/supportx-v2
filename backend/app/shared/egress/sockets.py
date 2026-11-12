"""The address a tenant-typed host may be reached at, for non-HTTP clients (audit #3).

`client.send` pins HTTP calls itself; IMAP and SMTP (and later LDAP, lane B, and fetch.py's DNS
pin, lane C's WP-057) speak other protocols, so they ask here first and connect to the address
returned, never to the name: a name resolved once and checked once cannot be rebound between the
check and the connection. TLS still verifies the certificate against the typed name.

The name is refused when it does not resolve, and when ANY of its answers is an address no
tenant may reach (`addresses.allowed`: private, loopback, link-local and cloud metadata, CGNAT,
reserved, and IPv6 forms carrying such an IPv4): picking a good answer from a mixed set would
let a rebinding name through. Only the installation's own configuration opens a private range.
The refusal says only `address_not_allowed`; which address or range it hit is logged here,
never returned to the tenant.
"""

import ipaddress

from app.core.logging import get_logger
from app.shared.egress.addresses import Allowance, IPAddress, allowed
from app.shared.egress.client import EgressError, Resolver, system_resolver

NOT_ALLOWED = "address_not_allowed"
UNRESOLVED = "unreachable"

log = get_logger(__name__)


async def pinned_address(
    host: str, port: int, allowance: Allowance, resolver: Resolver = system_resolver
) -> IPAddress:
    """The one address to connect to for `host:port`, or EgressError.

    `address_not_allowed` when any answer is not reachable for a tenant; `unreachable` when the
    name does not resolve. An address typed as such is judged the same way. It never checks
    `allowance.ports`: each caller limits its own protocol's ports (IMAP: `IMAP_PORTS`).
    """
    name = host.strip().strip("[]")
    try:
        answers: list[IPAddress] = [ipaddress.ip_address(name)]
    except ValueError:
        answers = await resolver(name, port)
    if not answers:
        raise EgressError(UNRESOLVED)
    refused = [ip for ip in answers if not allowed(ip, name, allowance)]
    if refused:
        # The detail stays here (operators); the tenant only learns the code.
        log.warning(
            "egress_address_refused", host=name, port=port, refused=[str(ip) for ip in refused]
        )
        raise EgressError(NOT_ALLOWED)
    return answers[0]


__all__ = ["NOT_ALLOWED", "UNRESOLVED", "pinned_address"]
