"""Vendor support grants (WP-057 S4c-1, REQ-SEC-045, D-173): pure rules, no I/O.

A tenant admin grants one named Extravis engineer temporary access. The rules here are the ones
the service applies before it touches the database or Keycloak; the database holds the same
limits as checks (migration 0179), so a bug in one is caught by the other.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

DEFAULT_LENGTH = timedelta(hours=24)  # D-173 (3)
MAX_TOTAL = timedelta(
    hours=72
)  # D-173 (3): never past 72 hours from the start, extensions included
MIN_LENGTH = timedelta(hours=1)
MAX_OPEN_GRANTS = 3  # lane B (6)
REASON_MAX = 500
NAME_MAX = 200
TICKET_MAX = 100
IP_LIST_MAX = 20
DEFAULT_EMAIL_DOMAINS = ("extravis.com",)  # lane B (1): an instance setting may widen it
# Any UUID gives a tag of the same length, so one probe tells whether an address can be tagged.
_PROBE_ID = uuid.UUID(int=0)


class Access(StrEnum):
    """What the support account may do (D-173 (6)): view only is preselected."""

    VIEW = "view"
    VIEW_AND_CHANGE = "view_and_change"


class GrantState(StrEnum):
    """Where a grant stands. Only the first two are open (count towards the limits)."""

    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    ENDED = "ended"
    REVOKED = "revoked"


OPEN_STATES = frozenset({GrantState.PENDING_VERIFICATION, GrantState.ACTIVE})


class Verification(StrEnum):
    """How the engineer is proven (D-173 (5)): their e-mail link, or an admin's call-back."""

    EMAIL = "email"
    OUT_OF_BAND = "out_of_band"


class Delivery(StrEnum):
    """How the engineer gets in.

    ACTIONS_EMAIL: no credential exists; Keycloak's actions e-mail to the engineer's mailbox has
    them verify, set a password and enrol a second factor, so only they can sign in.
    ONE_TIME_PASSWORD: the admin is shown a password once and passes it on; the admin could act
    as the engineer, and the grant says so (air-gapped installs, and D-173 as worded today).
    """

    ACTIONS_EMAIL = "actions_email"
    ONE_TIME_PASSWORD = "one_time_password"  # noqa: S105 - a delivery code, not a secret


# With mail, which path applies waits for Haider (item 14, 2026-11-20). Until then it is None:
# the grant is refused (lane B, 2026-11-19), as the admin path lets the admin be the engineer and
# D-173's core is "named and verified". His answer sets this one value: ACTIONS_EMAIL (lane B's
# and lane C's recommendation) or ONE_TIME_PASSWORD (D-173's wording today).
WITH_MAIL: Delivery | None = None
PENDING_DECISION = "vendor_support_email_pending_decision"

# The order the engineer must complete before any session (lane B (2)); on the one-time path
# Keycloak's own priorities decide the order, which is why that path carries its warning.
REQUIRED_ACTIONS = ("VERIFY_EMAIL", "UPDATE_PASSWORD", "CONFIGURE_TOTP")
OUT_OF_BAND_ACTIONS = ("UPDATE_PASSWORD", "CONFIGURE_TOTP")


def delivery_for(verification: "Verification", *, mail_available: bool) -> Delivery | None:
    """The one place that decides how the engineer gets in; None while that waits for Haider.

    Out-of-band (no mail to verify with) is always the one-time password, with its warning;
    with mail, `WITH_MAIL`.
    """
    if verification is Verification.OUT_OF_BAND or not mail_available:
        return Delivery.ONE_TIME_PASSWORD
    return WITH_MAIL


def admin_could_act_as_engineer(delivery: Delivery) -> bool:
    """Shown on the grant and in the audit: the admin held a credential (lane B (2))."""
    return delivery is Delivery.ONE_TIME_PASSWORD


def actions_for(verification: "Verification") -> tuple[str, ...]:
    """The Keycloak required actions on the account: verify the address only when e-mailed."""
    return OUT_OF_BAND_ACTIONS if verification is Verification.OUT_OF_BAND else REQUIRED_ACTIONS


def link_lifespan_seconds(now: datetime, ends_at: datetime) -> int:
    """The actions e-mail's link lasts until the grant ends, 24 hours at most, a minute at least."""
    left = int((ends_at - now).total_seconds())
    return max(60, min(left, int(DEFAULT_LENGTH.total_seconds())))


@dataclass(frozen=True)
class GrantRequest:
    """What the admin asked for, before any checks."""

    engineer_name: str
    engineer_email: str
    reason: str
    ticket_ref: str | None
    access: Access
    change_reason: str | None
    unmask_personal: bool
    hours: int | None  # None: the default length
    ip_allowlist: Sequence[str]
    verification: Verification
    confirmation_note: str | None


def email_domain(email: str) -> str | None:
    """The address's domain, lower-cased, or None when it is not one address."""
    text = email.strip()
    if text.count("@") != 1:
        return None
    local, domain = text.split("@")
    if not local or not domain or "." not in domain or any(c.isspace() for c in text):
        return None
    return domain.lower().rstrip(".")


def domain_allowed(email: str, allowed: Iterable[str]) -> bool:
    """The engineer's address is at one of the allowed domains (or a subdomain of one)."""
    domain = email_domain(email)
    if domain is None:
        return False
    wanted = {d.strip().lower().rstrip(".") for d in allowed if d.strip()}
    return any(domain == d or domain.endswith("." + d) for d in wanted)


def grant_problems(  # noqa: C901, PLR0912 - one check per field, flat, each its own code
    request: GrantRequest, *, allowed_domains: Iterable[str], open_grants: int, opted_out: bool
) -> list[tuple[str, str]]:
    """Every reason the grant can't be made, as (field, code) pairs; empty when it can."""
    problems: list[tuple[str, str]] = []
    if opted_out:
        problems.append(("grant", "vendor_support_disabled"))
    if open_grants >= MAX_OPEN_GRANTS:
        problems.append(("grant", "support_grants_limit"))
    name = request.engineer_name.strip()
    if not name or len(name) > NAME_MAX:
        problems.append(("engineer_name", "required" if not name else "too_long"))
    if email_domain(request.engineer_email) is None:
        problems.append(("engineer_email", "invalid_email"))
    elif not domain_allowed(request.engineer_email, allowed_domains):
        problems.append(("engineer_email", "support_email_domain_not_allowed"))
    elif account_email(request.engineer_email, _PROBE_ID) is None:
        problems.append(("engineer_email", "support_email_not_taggable"))
    reason = request.reason.strip()
    if not reason or len(reason) > REASON_MAX:
        problems.append(("reason", "required" if not reason else "too_long"))
    if request.ticket_ref is not None and len(request.ticket_ref.strip()) > TICKET_MAX:
        problems.append(("ticket_ref", "too_long"))
    if request.access is Access.VIEW_AND_CHANGE:
        change = (request.change_reason or "").strip()
        if not change or len(change) > REASON_MAX:
            problems.append(("change_reason", "required" if not change else "too_long"))
    if request.hours is not None and not (
        MIN_LENGTH <= timedelta(hours=request.hours) <= MAX_TOTAL
    ):
        problems.append(("hours", "support_grant_length"))
    if len(request.ip_allowlist) > IP_LIST_MAX:
        problems.append(("ip_allowlist", "too_many"))
    if request.verification is Verification.OUT_OF_BAND:
        note = (request.confirmation_note or "").strip()
        if not note or len(note) > REASON_MAX:
            problems.append(("confirmation_note", "required" if not note else "too_long"))
    return problems


def window(starts_at: datetime, hours: int | None) -> tuple[datetime, datetime]:
    """The grant's start and end: the default length unless hours are given."""
    length = DEFAULT_LENGTH if hours is None else timedelta(hours=hours)
    return starts_at, starts_at + length


def extended_end(starts_at: datetime, ends_at: datetime, extra_hours: int) -> datetime | None:
    """The new end after an extension, or None when it would pass 72 hours from the start."""
    if extra_hours < 1:
        return None
    new_end = ends_at + timedelta(hours=extra_hours)
    return new_end if new_end - starts_at <= MAX_TOTAL else None


def is_open(state: str) -> bool:
    """The grant still counts: waiting for the engineer, or in use."""
    return state in {s.value for s in OPEN_STATES}


def due_to_end(state: str, ends_at: datetime, now: datetime) -> bool:
    """An open grant whose time is up (the 30-second schedule ends it)."""
    return is_open(state) and ends_at <= now


LOCAL_PART_MAX = 64  # RFC 5321: the part before the @


def account_email(engineer_email: str, grant_id: uuid.UUID) -> str | None:
    """The support account's own address, or None when one can't be made (lane B (1)).

    The shared realm allows one account per address (ADR-006, `duplicateEmailsAllowed` false),
    so the engineer's own address would collide with their account or another tenant's grant. A
    plus-address (`omar+sx-<grant hex>@extravis.com`) reaches the same mailbox, so Keycloak's
    verify-e-mail step still proves the engineer (lane B's condition 2). The coordinator chose
    it (2026-11-19); this one function is what changes if SupportX's own link replaces it.

    Refused: an address that already has a `+` tag, and one whose local part would pass 64
    characters. The grant ID is a UUIDv7 as lowercase hex (never guessable from a sequence); the
    domain is the real address's, so the domain check on the real address covers it.
    """
    domain = email_domain(engineer_email)
    if domain is None:
        return None
    local = engineer_email.strip().split("@")[0].lower()
    if "+" in local:
        return None
    tagged = f"{local}+sx-{grant_id.hex}"
    if len(tagged) > LOCAL_PART_MAX:
        return None
    return f"{tagged}@{domain}"


def support_username(grant_id: str) -> str:
    """The temporary account's sign-in name in the tenant's realm (one per grant, never reused)."""
    return f"extravis-support-{grant_id}"
