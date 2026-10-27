"""The installation's password policy (WP-039 session 2; REQ-SEC-005; D-089 D1 c, D2).

Keycloak keeps the passwords and checks them on every page that sets one (sign-up never exists;
the invitation, reset, "new password at next sign-in" and my-account pages are Keycloak's).
SupportX only decides the rules: a tenant admin edits them in Admin > Sign-in and security, and a
worker writes them into the realm as Keycloak's policy string (`to_keycloak`). A shared realm has
one policy, so this is installation-wide; on multi-tenant installations it is the platform's
and cannot be edited (per-organization rules are V1, D-089 D1).

Pure rules, no I/O. Defaults and floors: Appendix A (12 characters, at least 8; the last 5
refused; no expiry; the breached list on).
"""

from dataclasses import dataclass

from app.core.errors import FieldError

MIN_LENGTH_FLOOR, MAX_MIN_LENGTH = 8, 64
MAX_HISTORY = 24
MAX_EXPIRY_DAYS = 365
# Keycloak hashes every attempt; a ceiling keeps one request from costing seconds of CPU.
MAX_LENGTH = 128
# The file in Keycloak's password-blacklists folder (deploy/…/keycloak/password-blacklists).
BREACHED_LIST = "supportx-breached.txt"


@dataclass(frozen=True)
class PasswordPolicy:
    """What a new password must be."""

    min_length: int = 12
    upper: bool = True
    lower: bool = True
    digits: bool = True
    special: bool = True
    history: int = 5  # the last N passwords are refused; 0 = any
    expiry_days: int = 0  # 0 = never expires
    breached_check: bool = True


FIELDS = {
    "min_length": "password_min_length",
    "upper": "password_upper",
    "lower": "password_lower",
    "digits": "password_digits",
    "special": "password_special",
    "history": "password_history",
    "expiry_days": "password_expiry_days",
    "breached_check": "password_breached_check",
}


def _range(field: str, value: int, low: int, high: int) -> FieldError | None:
    if low <= value <= high:
        return None
    return FieldError(
        field=field,
        code="password_policy_out_of_range",
        message_key="errors.field.password_policy_out_of_range",
        params={"min": low, "max": high},
    )


def problems(policy: PasswordPolicy) -> list[FieldError]:
    """Each value outside its range, at its settings field with the limits (D-091)."""
    found = [
        _range(FIELDS["min_length"], policy.min_length, MIN_LENGTH_FLOOR, MAX_MIN_LENGTH),
        _range(FIELDS["history"], policy.history, 0, MAX_HISTORY),
        _range(FIELDS["expiry_days"], policy.expiry_days, 0, MAX_EXPIRY_DAYS),
    ]
    return [problem for problem in found if problem is not None]


def to_keycloak(policy: PasswordPolicy) -> str:
    """Keycloak's `passwordPolicy` for the realm (built-in policies only, no extension)."""
    parts = [f"length({policy.min_length})", f"maxLength({MAX_LENGTH})"]
    parts += [
        name
        for name, wanted in (
            ("upperCase(1)", policy.upper),
            ("lowerCase(1)", policy.lower),
            ("digits(1)", policy.digits),
            ("specialChars(1)", policy.special),
        )
        if wanted
    ]
    parts += ["notUsername", "notEmail"]
    if policy.history:
        parts.append(f"passwordHistory({policy.history})")
    if policy.expiry_days:
        parts.append(f"forceExpiredPasswordChange({policy.expiry_days})")
    if policy.breached_check:
        parts.append(f"passwordBlacklist({BREACHED_LIST})")
    return " and ".join(parts)
