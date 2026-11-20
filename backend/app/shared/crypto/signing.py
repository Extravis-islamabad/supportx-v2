"""Signing outgoing webhook bodies, and checking them (WP-057 S5a; WP-055 reuses it). Pure.

One scheme for every SupportX webhook (the coordinator, 2026-11-20):

- `X-SupportX-Timestamp`: the sending time, Unix seconds.
- `X-SupportX-Signature`: `v1=<hex>`, HMAC-SHA256 over `"<timestamp>.<body>"` with the
  destination's own secret. During a secret's rotation both are active: the header carries one
  `v1=` value per secret, comma-separated, and a receiver accepts any of them.

A receiver checks the timestamp is within five minutes of its clock (a replayed request is
refused) and compares in constant time. The secret is never logged or echoed by this module.
"""

import hashlib
import hmac
from collections.abc import Iterable, Mapping, Sequence

SIGNATURE_HEADER = "X-SupportX-Signature"
TIMESTAMP_HEADER = "X-SupportX-Timestamp"
VERSION = "v1"
TOLERANCE_SECONDS = 300  # five minutes either way
OFFERED_MAX = 4  # signatures checked per request (two secrets in a rotation, with room)
TIMESTAMP_DIGITS_MAX = 12  # Unix seconds for the next thirty thousand years


def _mac(secret: bytes, timestamp: int, body: bytes) -> str:
    message = str(timestamp).encode("ascii") + b"." + body
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def signature(secrets: Sequence[bytes], timestamp: int, body: bytes) -> str:
    """The signature header's value: one `v1=` per active secret (two during a rotation)."""
    if not secrets:
        msg = "a webhook needs at least one secret to sign with"
        raise ValueError(msg)
    return ",".join(f"{VERSION}={_mac(secret, timestamp, body)}" for secret in secrets)


def sign(secrets: Sequence[bytes], timestamp: int, body: bytes) -> dict[str, str]:
    """The two headers to send with `body`."""
    return {
        TIMESTAMP_HEADER: str(timestamp),
        SIGNATURE_HEADER: signature(secrets, timestamp, body),
    }


def _values(header: str) -> Iterable[str]:
    for part in header.split(","):
        version, _, value = part.strip().partition("=")
        if version == VERSION and value:
            yield value


def verify(
    secrets: Sequence[bytes],
    headers: Mapping[str, str],
    body: bytes,
    *,
    now: int,
    tolerance: int = TOLERANCE_SECONDS,
) -> bool:
    """Whether `body` was signed with one of `secrets`, within `tolerance` seconds of `now`.

    Constant-time comparisons; an unknown version, a missing header or a timestamp out of the
    window is refused. Two secrets may be active at once (a rotation overlap).
    """
    lowered = {k.lower(): v for k, v in headers.items()}
    raw_time = lowered.get(TIMESTAMP_HEADER.lower(), "")
    header = lowered.get(SIGNATURE_HEADER.lower(), "")
    # Digits only (no sign, spaces or underscores, which int() would take).
    if not raw_time.isascii() or not raw_time.isdigit() or len(raw_time) > TIMESTAMP_DIGITS_MAX:
        return False
    timestamp = int(raw_time)
    if abs(now - timestamp) > tolerance:
        return False
    offered = list(_values(header))[:OFFERED_MAX]  # never an unbounded loop of comparisons
    found = False
    for secret in secrets:
        expected = _mac(secret, timestamp, body)
        for value in offered:
            # Every pair is compared, so the time taken never tells which one matched.
            found |= hmac.compare_digest(expected, value)
    return found
