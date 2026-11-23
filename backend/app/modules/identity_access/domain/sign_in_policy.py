"""Who may sign in how (REQ-SEC-009, REQ-SEC-026; WP-057 S1b). Pure: no I/O.

**Single sign-on required.** A tenant may require single sign-on for nobody (off), technicians
or everyone. A password (or directory) sign-in by someone in scope is refused, unless they are a
named break-glass admin with MFA enrolled: the tenant is never locked out when its identity
provider fails (and every such sign-in alerts the other admins, the service's part).

**Turning it on** is refused without at least one active break-glass admin, and removing the
last one while it is on is refused too (the coordinator's rule).

**MFA after single sign-on** (REQ-SEC-026): by default the identity provider's MFA is trusted and
SupportX asks no code; with `also_require_mfa` the person's SupportX MFA applies as after a
password.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.modules.identity_access.domain.sign_in import SignInMethod


class SsoRequired(StrEnum):
    """For whom single sign-on is the only way in."""

    OFF = "off"
    TECHNICIANS = "technicians"
    EVERYONE = "everyone"


SSO_REQUIRED = "sso_required"  # the refusal's code (labelled)
BREAK_GLASS_NEEDS_MFA = "break_glass_needs_mfa"
NO_BREAK_GLASS_ADMIN = "sso_required_needs_break_glass"
LAST_BREAK_GLASS_ADMIN = "last_break_glass_admin"


@dataclass(frozen=True)
class Person:
    """What the policy needs to know about whoever is signing in."""

    technician: bool
    break_glass: bool
    mfa_enrolled: bool


@dataclass(frozen=True)
class Verdict:
    """Allowed or why not, and whether this is a break-glass sign-in (alert and mark it)."""

    refusal: str | None = None
    break_glass: bool = False


def in_scope(rule: SsoRequired, person: Person) -> bool:
    """Whether single sign-on is required of this person."""
    if rule is SsoRequired.EVERYONE:
        return True
    return rule is SsoRequired.TECHNICIANS and person.technician


def judge(rule: SsoRequired, person: Person, method: SignInMethod) -> Verdict:
    """The verdict for a sign-in by `method` (from the verified token, never the browser)."""
    if method is SignInMethod.SINGLE_SIGN_ON or not in_scope(rule, person):
        return Verdict()
    if not person.break_glass:
        return Verdict(refusal=SSO_REQUIRED)
    if not person.mfa_enrolled:
        return Verdict(refusal=BREAK_GLASS_NEEDS_MFA)
    return Verdict(break_glass=True)


def requires_supportx_mfa(method: SignInMethod, *, also_require_mfa: bool) -> bool:
    """Whether SupportX's own MFA applies to this sign-in (REQ-SEC-026 AC1, AC2)."""
    return method is not SignInMethod.SINGLE_SIGN_ON or also_require_mfa


def change_refusal(
    rule: SsoRequired, active_break_glass_admins: int, *, removing_admin: bool
) -> str | None:
    """Why a setting or break-glass change may not be saved, or None.

    `active_break_glass_admins` counts them as they would be after the change; `removing_admin`
    says the change takes an admin away (the last one) rather than turning the rule on.
    """
    if rule is SsoRequired.OFF or active_break_glass_admins > 0:
        return None
    return LAST_BREAK_GLASS_ADMIN if removing_admin else NO_BREAK_GLASS_ADMIN
