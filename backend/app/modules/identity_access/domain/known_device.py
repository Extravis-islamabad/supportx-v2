"""Whether a person has signed in from this browser or device before (REQ-SEC-033; WP-057 S2b-1).

Pure: no I/O. A "device" is the browser and system code (domain/sign_in.device, never the raw
User-Agent) plus the network the address belongs to: its /24 for IPv4, its /48 for IPv6, so a home
connection that changes its last octet stays the same device. Only a keyed fingerprint is kept,
HMAC-SHA256 under the "known-device" key (HKDF of the ADR-048 ring, never the session or API-key
key): the table alone says nothing about where or on what anyone signed in.

The key comes from the session ring, so a rotated ring must still recognise devices: a sign-in is
checked against the fingerprint under every listed key, and a match is moved to the newest.
"""

import hashlib
import hmac
import ipaddress
import uuid
from collections.abc import Sequence

from app.modules.identity_access.domain.place import parse_address

IPV4_PREFIX = 24
IPV6_PREFIX = 48
FINGERPRINT_BYTES = 32


def network_part(value: str | None) -> str | None:
    """The address's network as text (10.1.2.0/24, 2001:db8:1::/48), or None without one."""
    address = parse_address(value)
    if address is None:
        return None
    prefix = IPV4_PREFIX if address.version == 4 else IPV6_PREFIX  # noqa: PLR2004 - IP version
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))


def fingerprint(key: bytes, user_id: uuid.UUID, device: str | None, ip: str | None) -> bytes | None:
    """The 32-byte fingerprint of this person's sign-in, or None when nothing identifies it."""
    network = network_part(ip)
    if device is None and network is None:
        return None
    message = b"\x00".join((user_id.bytes, (device or "-").encode(), (network or "-").encode()))
    return hmac.new(key, message, hashlib.sha256).digest()


def fingerprints(
    keys: Sequence[bytes], user_id: uuid.UUID, device: str | None, ip: str | None
) -> tuple[bytes, ...]:
    """The fingerprint under each key, newest key first (empty when nothing identifies it)."""
    found = [fingerprint(key, user_id, device, ip) for key in keys]
    return tuple(print_ for print_ in found if print_ is not None)
