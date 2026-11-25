"""The security overview's weak-choice flags (WP-057 S4d): pure rules, no I/O.

The overview (Admin > Security, top) gathers counts the other security screens already show and
flags choices weaker than recommended. Every threshold here is a **recommendation only**: nothing
is enforced, nothing changes by itself, and each flag links to the card where the admin decides
(the coordinator, 2026-11-17; the PR lists them for the product owner).

Flags carry codes and numbers only (lane B's condition 1): no names, e-mails or addresses.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

# --- recommendations (never enforced) ------------------------------------------------------------

RECOMMENDED_PASSWORD_MIN = 12
RECOMMENDED_CONSOLE_IDLE_SECONDS = 60 * 60  # an hour without activity
RECOMMENDED_CONSOLE_ABSOLUTE_SECONDS = 12 * 60 * 60  # a working day
RECOMMENDED_KEY_LIFETIME_DAYS = 366
EXPIRY_WARN_DAYS = 30  # REQ-SEC-011's first notice (domain/expiry.py THRESHOLDS_DAYS)
EXPIRY_URGENT_DAYS = 7
FAILED_SIGN_INS_WINDOW_DAYS = 7


class SecuritySeverity(StrEnum):
    """How much a flag matters: `high` first, then `medium`, then `low`."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


_ORDER = {SecuritySeverity.HIGH: 0, SecuritySeverity.MEDIUM: 1, SecuritySeverity.LOW: 2}


class SecurityArea(StrEnum):
    """The overview's tiles; each flag belongs to one and links to its card."""

    MFA = "mfa"
    SIGN_IN = "sign_in"
    PASSWORDS = "passwords"
    SESSIONS = "sessions"
    NETWORK = "network"
    KEYS = "keys"
    SERVICE_ACCOUNTS = "service_accounts"
    ENCRYPTION = "encryption"
    SIGN_IN_EVENTS = "sign_in_events"
    VENDOR_SUPPORT = "vendor_support"  # WP-057 S4c (D-173)
    SIEM = "siem"  # D-181: audit streaming


@dataclass(frozen=True)
class Flag:
    """One weaker-than-recommended choice: a code (`security_flag.<code>`), its tile and numbers."""

    code: str
    area: SecurityArea
    severity: SecuritySeverity
    count: int | None = None  # how many things it is about, when it is about things


@dataclass(frozen=True)
class Choices:
    """What the flags read: settings and counts, already gathered by the service."""

    # MFA: roles whose mode is `off`, among roles people hold (from mfa.list_policies).
    roles_without_mfa: int
    admins_without_mfa: bool  # tenant administration held by a role whose MFA is off
    sso_required: bool
    password_min_length: int
    password_breached_check: bool
    password_expiry_days: int
    console_idle_seconds: int
    console_absolute_seconds: int
    console_network_rule: bool
    api_network_rule: bool
    allow_non_expiring_keys: bool
    key_max_lifetime_days: int
    keys_out_of_policy: int
    keys_unused: int
    service_accounts_without_owner: int
    # Days left on the soonest SSO certificate or secret; None: none set.
    sso_expiry_days_left: int | None
    fields_not_sealed: int  # sensitive fields still `sealing` or `opening`
    failed_sign_ins: int  # in the last FAILED_SIGN_INS_WINDOW_DAYS
    locked_sign_ins: int
    # Vendor support grants ended over 24 hours ago whose account is not confirmed gone (lane B).
    support_removals_stuck: int = 0
    plaintext_siem_destinations: int = 0  # D-181: syslog sent without TLS
    # WP-057 S5c: directories giving managed access with no successful sync for over a day
    # (the access stays; the overview makes it visible, the coordinator's condition).
    directory_access_stale: int = 0


def _expiry_flags(days_left: int | None) -> Iterable[Flag]:
    if days_left is None:
        return
    if days_left < 0:
        yield Flag("sso_credential_expired", SecurityArea.SIGN_IN, SecuritySeverity.HIGH)
    elif days_left <= EXPIRY_URGENT_DAYS:
        yield Flag(
            "sso_credential_expires_soon", SecurityArea.SIGN_IN, SecuritySeverity.HIGH, days_left
        )
    elif days_left <= EXPIRY_WARN_DAYS:
        yield Flag(
            "sso_credential_expires", SecurityArea.SIGN_IN, SecuritySeverity.MEDIUM, days_left
        )


def _password_flags(c: Choices) -> Iterable[Flag]:
    if c.sso_required:
        return  # nobody signs in with a SupportX password: the policy is moot
    if c.password_min_length < RECOMMENDED_PASSWORD_MIN:
        yield Flag(
            "password_short", SecurityArea.PASSWORDS, SecuritySeverity.MEDIUM, c.password_min_length
        )
    if not c.password_breached_check:
        yield Flag("password_breached_off", SecurityArea.PASSWORDS, SecuritySeverity.MEDIUM)
        if c.password_expiry_days > 0:
            # NIST SP 800-63B: forced expiry without a breach check pushes weaker patterns.
            yield Flag(
                "password_expiry_without_check", SecurityArea.PASSWORDS, SecuritySeverity.LOW
            )


def _switch_flags(c: Choices) -> Iterable[Flag]:
    """Yes-or-no choices: a flag when the weaker one is chosen."""
    weak = (
        (c.admins_without_mfa, "admins_without_mfa", SecurityArea.MFA, SecuritySeverity.HIGH),
        (
            c.console_idle_seconds > RECOMMENDED_CONSOLE_IDLE_SECONDS,
            "console_idle_long",
            SecurityArea.SESSIONS,
            SecuritySeverity.LOW,
        ),
        (
            c.console_absolute_seconds > RECOMMENDED_CONSOLE_ABSOLUTE_SECONDS,
            "console_session_long",
            SecurityArea.SESSIONS,
            SecuritySeverity.LOW,
        ),
        (
            not c.console_network_rule,
            "console_open_network",
            SecurityArea.NETWORK,
            SecuritySeverity.LOW,
        ),
        (not c.api_network_rule, "api_open_network", SecurityArea.NETWORK, SecuritySeverity.LOW),
        (
            c.allow_non_expiring_keys,
            "keys_never_expire",
            SecurityArea.KEYS,
            SecuritySeverity.MEDIUM,
        ),
    )
    for chosen, code, area, severity in weak:
        if chosen:
            yield Flag(code, area, severity)


def _count_flags(c: Choices) -> Iterable[Flag]:
    """Things to look at: a flag with the count when there is at least one."""
    counted = (
        (c.roles_without_mfa, "roles_without_mfa", SecurityArea.MFA, SecuritySeverity.MEDIUM),
        (c.keys_out_of_policy, "keys_out_of_policy", SecurityArea.KEYS, SecuritySeverity.MEDIUM),
        (c.keys_unused, "keys_unused", SecurityArea.KEYS, SecuritySeverity.LOW),
        (
            c.service_accounts_without_owner,
            "service_accounts_without_owner",
            SecurityArea.SERVICE_ACCOUNTS,
            SecuritySeverity.MEDIUM,
        ),
        (c.fields_not_sealed, "fields_still_moving", SecurityArea.ENCRYPTION, SecuritySeverity.LOW),
        (
            c.locked_sign_ins,
            "sign_ins_locked",
            SecurityArea.SIGN_IN_EVENTS,
            SecuritySeverity.MEDIUM,
        ),
        (
            c.support_removals_stuck,
            "support_removals_stuck",
            SecurityArea.VENDOR_SUPPORT,
            SecuritySeverity.HIGH,
        ),
        (
            c.plaintext_siem_destinations,
            "siem_plaintext",
            SecurityArea.SIEM,
            SecuritySeverity.MEDIUM,
        ),
        (
            c.directory_access_stale,
            "directory_access_stale",
            SecurityArea.SIGN_IN,  # its own tile comes with the S5c-2 screens
            SecuritySeverity.MEDIUM,
        ),
    )
    for count, code, area, severity in counted:
        if count > 0:
            yield Flag(code, area, severity, count)


def flags(c: Choices) -> list[Flag]:
    """Every weaker-than-recommended choice, most severe first (ties: the tiles' order)."""
    return sort_flags(
        [
            *_switch_flags(c),
            *_count_flags(c),
            *_expiry_flags(c.sso_expiry_days_left),
            *_password_flags(c),
        ]
    )


def sort_flags(found: Sequence[Flag]) -> list[Flag]:
    """Most severe first; within a severity, in the tiles' order (stable)."""
    areas = list(SecurityArea)
    return sorted(found, key=lambda f: (_ORDER[f.severity], areas.index(f.area)))


RECOMMENDATIONS: dict[str, int | bool] = {
    "password_min_length": RECOMMENDED_PASSWORD_MIN,
    "password_breached_check": True,
    "console_idle_seconds": RECOMMENDED_CONSOLE_IDLE_SECONDS,
    "console_absolute_seconds": RECOMMENDED_CONSOLE_ABSOLUTE_SECONDS,
    "key_max_lifetime_days": RECOMMENDED_KEY_LIFETIME_DAYS,
    "allow_non_expiring_keys": False,
    "sso_expiry_warn_days": EXPIRY_WARN_DAYS,
    "sso_expiry_urgent_days": EXPIRY_URGENT_DAYS,
}
"""The recommendations, as the API states them (shown beside each flag; never enforced)."""
