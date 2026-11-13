"""People kept informed by e-mail on an incident (WP-046a S6; REQ-INC-066). Pure, no I/O.

A record may carry up to `MAX` addresses (`work_items.notify_emails`) that get its public
replies, never its notes. The first mail's Cc may join them (a type setting, on by default), only
when the mailbox's server vouched for the sender (lane B: a forged From must not copy every reply
to its Cc), within the same cap and never with one of our own addresses or the requester's.

Each mail to such an address carries a link to stop them (lane B's conditions): a random token,
only its hash kept, for one record and one address, single use, and good until the earliest of
the record closed plus `AFTER_CLOSE`, `MAX_AGE`, or the mail content's own retention:
min(closed + 30 d, sent + 180 d, sent + mail_content_retention_days), so a stored mail body never
holds a live token past its purge (lane B).
"""

import re
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

MAX = 20
# The field codes `problems` gives (labels: errors.field.*; checked in test_domain).
FIELD_PROBLEMS = frozenset({"invalid_email", "too_many_addresses"})
AFTER_CLOSE = timedelta(days=30)
MAX_AGE = timedelta(days=180)
_EMAIL = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;]+$")
ADDRESS_MAX = 254  # RFC 5321


def clean(values: Iterable[str]) -> tuple[list[str], list[str]]:
    """(valid, invalid): trimmed, lower-cased, de-duplicated in order."""
    cleaned: list[str] = []
    invalid: list[str] = []
    for raw in values:
        value = raw.strip().lower()
        if not value:
            continue
        if not _EMAIL.fullmatch(value) or len(value) > ADDRESS_MAX:
            invalid.append(raw.strip())
        elif value not in cleaned:
            cleaned.append(value)
    return cleaned, invalid


def problems(values: Sequence[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """The addresses to keep, and (field, code) problems: a bad address, or more than MAX."""
    cleaned, invalid = clean(values)
    found: list[tuple[str, str]] = []
    if invalid:
        found.append(("notify_emails", "invalid_email"))
    if len(cleaned) > MAX:
        found.append(("notify_emails", "too_many_addresses"))
    return cleaned, found


def from_first_mail(cc: Iterable[str], *, excluded: Iterable[str]) -> list[str]:
    """The first mail's Cc that join the list: valid ones, not ours or the requester's, ≤ MAX."""
    skip = {address.strip().lower() for address in excluded}
    cleaned, _ = clean(cc)
    return [address for address in cleaned if address not in skip][:MAX]


def link_expiry(
    now: datetime, *, closed_at: datetime | None, retention: timedelta | None = None
) -> datetime:
    """When a stop link sent now stops working (the earliest of the three limits)."""
    limits = [now + MAX_AGE]
    if closed_at is not None:
        limits.append(closed_at + AFTER_CLOSE)
    if retention is not None:
        limits.append(now + retention)
    return min(limits)


def masked(address: str) -> str:
    """`sara@acme.test` → `s***@acme.test`: what a log or the stop page may show."""
    local, at, domain = address.partition("@")
    return f"{local[:1]}***{at}{domain}" if at else "***"
