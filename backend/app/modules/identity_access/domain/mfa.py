"""MFA policy rules, pure (WP-039 session 3; REQ-SEC-022, 024, 025; D-089 D5, D7; D-104).

Keycloak keeps the authenticator and recovery-code credentials and asks for them at sign-in
(its built-in conditional second step: anyone with a code generator configured is asked). What
SupportX decides is who must enrol, and when:

- a mode per role and tenant: off, optional or required. Appendix A defaults: required for the
  tenant administrator, security administrator, auditor and technician roles; optional for the
  requester and for custom roles. A person's mode is the strictest of their roles here;
- required MFA gives a grace period (Appendix A: 7 days, at most 30) from the moment it first
  became required for the person; after it, a person who has not enrolled can only enrol:
  Keycloak's own required action makes them, at their next sign-in, before anything else;
- one Keycloak user serves all of a person's tenants, so the strictest tenant wins (D-089): any
  tenant that requires MFA makes the person enrol.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.modules.identity_access.domain.permissions import (
    AUDITOR,
    REQUESTER,
    SECURITY_ADMIN,
    TECHNICIAN,
    TENANT_ADMIN,
)

Mode = Literal["off", "optional", "required"]
MODES: tuple[Mode, ...] = ("off", "optional", "required")
_RANK: dict[Mode, int] = {"off": 0, "optional": 1, "required": 2}
DEFAULT_MODES: dict[str, Mode] = {
    TENANT_ADMIN: "required",
    SECURITY_ADMIN: "required",
    AUDITOR: "required",
    TECHNICIAN: "required",
    REQUESTER: "optional",
}
CUSTOM_ROLE_DEFAULT: Mode = "optional"
GRACE_DAYS_DEFAULT, MAX_GRACE_DAYS = 7, 30
# Keycloak's required actions an enrolment runs: a code generator, then recovery codes.
ENROL_ACTIONS = ("CONFIGURE_TOTP", "CONFIGURE_RECOVERY_AUTHN_CODES")
# Keycloak's credential types SupportX looks for and an admin reset removes.
MFA_CREDENTIALS = frozenset({"otp", "recovery-authn-codes"})


def default_mode(role_key: str | None) -> Mode:
    """A role's mode before any admin chose one (system roles by key; custom roles optional)."""
    if role_key is None:
        return CUSTOM_ROLE_DEFAULT
    return DEFAULT_MODES.get(role_key, CUSTOM_ROLE_DEFAULT)


def strictest(modes: list[Mode]) -> Mode:
    """The strictest of several modes (a person with no roles: off)."""
    return max(modes, key=lambda mode: _RANK[mode], default="off")


@dataclass(frozen=True)
class MfaStatus:
    """A person's MFA situation in one tenant, as their screens show it."""

    mode: Mode
    enrolled: bool
    due_at: datetime | None  # required and not enrolled: enrol by then

    def must_enrol(self, now: datetime) -> bool:
        """Past the grace period without an authenticator: enrolling is all they may do."""
        return self.due_at is not None and now >= self.due_at


def status(
    mode: Mode,
    *,
    enrolled: bool,
    required_since: datetime | None,
    grace_days: int,
) -> MfaStatus:
    """The person's status from their mode, enrolment and when MFA became required."""
    if mode != "required" or enrolled or required_since is None:
        return MfaStatus(mode, enrolled, None)
    return MfaStatus(mode, enrolled, required_since + timedelta(days=grace_days))
