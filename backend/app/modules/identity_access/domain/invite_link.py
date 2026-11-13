"""A copied invite link, the person's side (REQ-SEC-021; WP-057 S2b-2; lane B). Pure: no I/O.

Keycloak checks the new password against the realm's policy and refuses with a message key; the
person is told which rule in their language (`refusal`), never Keycloak's text. A key SupportX
does not know is a plain "not accepted": never shown raw.
"""

from app.modules.identity_access.domain.password_policy import MAX_LENGTH

# Keycloak's policy message keys (26.x) → SupportX's field error codes.
REFUSALS = {
    "invalidPasswordMinLengthMessage": "password_too_short",
    "invalidPasswordMaxLengthMessage": "password_too_long",  # TOO_LONG
    "invalidPasswordMinUpperCaseCharsMessage": "password_needs_upper",
    "invalidPasswordMinLowerCaseCharsMessage": "password_needs_lower",
    "invalidPasswordMinDigitsMessage": "password_needs_digit",
    "invalidPasswordMinSpecialCharsMessage": "password_needs_special",
    "invalidPasswordNotUsernameMessage": "password_is_username",
    "invalidPasswordNotEmailMessage": "password_is_email",
    "invalidPasswordHistoryMessage": "password_used_before",
    "invalidPasswordBlacklistedMessage": "password_breached",
}
REJECTED = "password_rejected"
TOO_LONG = "password_too_long"
INVALID = "invite_link_invalid"  # every way a link does not work: one answer (lane B)


def refusal(message: str | None) -> str:
    """The field error code for Keycloak's refusal message key."""
    return REFUSALS.get((message or "").strip(), REJECTED)


def too_long(password: str) -> bool:
    """Longer than Keycloak is ever asked to hash (MAX_LENGTH)."""
    return len(password) > MAX_LENGTH


def token_shape_ok(token: str) -> bool:
    """A copied token's shape: 43 base64url characters (32 bytes), nothing else is looked up."""
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    return len(token) == 43 and set(token) <= allowed  # noqa: PLR2004 - 32 bytes, base64url
