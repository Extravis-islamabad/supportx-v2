"""Which Keycloak user events become a notice to the person (REQ-SEC-033 part 2). Pure: no I/O.

Read by the same events import as the sign-in log (domain/sign_in_import.py), never written to
that log. Keycloak 25+ types only: the deprecated UPDATE_PASSWORD / UPDATE_TOTP / REMOVE_TOTP are
still emitted beside them and are never read, so nothing is told twice.

- A temporary lock-out: when the account opens again. Keycloak's events do not say; with the
  realm's LINEAR strategy (LOCKOUT, REQ-SEC-005) the k-th lock-out inside `max_delta_seconds`
  waits k times `wait_increment_seconds`, at most `max_wait_seconds`. Our marks can only
  undercount k, so the time is a lower bound: "at the earliest" (lane B).
- A password set or changed, or an MFA method added or removed, by the person in Keycloak's
  pages. An admin's MFA reset raises no user event (the admin API) and has its own notice.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.modules.identity_access.domain.mfa import MFA_CREDENTIALS

LOCKED_OUT = "USER_DISABLED_BY_TEMPORARY_LOCKOUT"
CREDENTIAL_UPDATED = "UPDATE_CREDENTIAL"
CREDENTIAL_REMOVED = "REMOVE_CREDENTIAL"
NOTICE_TYPES = (LOCKED_OUT, CREDENTIAL_UPDATED, CREDENTIAL_REMOVED)
PASSWORD = "password"  # noqa: S105 - Keycloak's credential type name, not a secret
# MFA in SupportX (domain/mfa.py) and the passkeys Keycloak may offer beside it.
MFA_TYPES = MFA_CREDENTIALS | {"webauthn", "webauthn-passwordless"}


class NoticeKind(StrEnum):
    """What the person is told (stored as `security_notice_marks.kind`)."""

    LOCKED_OUT = "locked_out"
    PASSWORD_CHANGED = "password_changed"  # noqa: S105 - a notice kind, not a secret
    PASSWORD_SET = "password_set"  # noqa: S105 - a first password (lane B): kept quiet
    MFA_ADDED = "mfa_added"
    MFA_REMOVED = "mfa_removed"


@dataclass(frozen=True)
class Lockout:
    """The realm's brute-force lock-out (REQ-SEC-005 AC2, D-104): one copy, tooling sets it."""

    failure_factor: int = 5
    wait_increment_seconds: int = 900
    max_wait_seconds: int = 3600
    max_delta_seconds: int = 43200

    def realm(self) -> dict[str, object]:
        """The realm representation's fields (tooling/keycloak_identity.py)."""
        return {
            "bruteForceProtected": True,
            "bruteForceStrategy": "LINEAR",
            "failureFactor": self.failure_factor,
            "waitIncrementSeconds": self.wait_increment_seconds,
            "maxFailureWaitSeconds": self.max_wait_seconds,
            "maxDeltaTimeSeconds": self.max_delta_seconds,
        }

    def opens_at(self, locked_at: datetime, earlier: list[datetime]) -> datetime:
        """When a lock-out at `locked_at` ends, given the person's earlier lock-outs."""
        window = locked_at - timedelta(seconds=self.max_delta_seconds)
        count = 1 + sum(1 for at in earlier if window <= at < locked_at)
        wait = min(self.max_wait_seconds, self.wait_increment_seconds * count)
        return locked_at + timedelta(seconds=wait)


LOCKOUT = Lockout()


def kind_of(event_type: str, credential_type: str | None) -> NoticeKind | None:
    """The notice an event gives, or None (not one the person is told of)."""
    if event_type == LOCKED_OUT:
        return NoticeKind.LOCKED_OUT
    if event_type == CREDENTIAL_UPDATED:
        if credential_type == PASSWORD:
            return NoticeKind.PASSWORD_CHANGED
        return NoticeKind.MFA_ADDED if credential_type in MFA_TYPES else None
    if event_type == CREDENTIAL_REMOVED:
        return NoticeKind.MFA_REMOVED if credential_type in MFA_TYPES else None
    return None


LOCKOUT_NOTICE_EVERY = timedelta(hours=1)  # lane B: a known name can be locked out every 15 min
MARK_RETENTION = timedelta(days=30)  # well past max_delta_seconds (lane B)


def lockout_quiet(locked_at: datetime, last_told: datetime | None) -> bool:
    """Whether a lock-out notice stays unsent: one was sent to the person within the hour."""
    return last_told is not None and locked_at - last_told < LOCKOUT_NOTICE_EVERY
