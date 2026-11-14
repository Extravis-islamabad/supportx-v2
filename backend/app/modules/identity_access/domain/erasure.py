"""Person erasure (GDPR art. 17): states, steps, codes. Pure Python (D-171, ADR-052).

An erasure is requested by one tenant admin and approved by another; then the erasure job runs
its steps in a fixed order (ADR-052 §3). `step` on the row is the next step to run, so a run
that stopped resumes there. Everything here is a stable code with labels in en/ar/ur; nothing
here does I/O.
"""

import base64
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum


class ErasureState(StrEnum):
    """Where an erasure stands (`person_erasure.state.<code>` labels)."""

    REQUESTED = "requested"
    APPROVED = "approved"
    RUNNING = "running"
    DONE = "done"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


# One open erasure per person (partial unique index uq_person_erasures_open, migration 0161).
# A failed erasure stays open: the person may be half-erased, so nothing new may start.
OPEN_STATES: frozenset[ErasureState] = frozenset(
    {ErasureState.REQUESTED, ErasureState.APPROVED, ErasureState.RUNNING, ErasureState.FAILED}
)
# States the job runs (or resumes) in.
RUNNABLE_STATES: frozenset[ErasureState] = frozenset({ErasureState.APPROVED, ErasureState.RUNNING})


class ErasureReason(StrEnum):
    """Why the person is erased (`person_erasure.reason.<code>` labels). A small fixed list."""

    SUBJECT_REQUEST = "subject_request"  # the person asked (GDPR art. 17(1))
    NO_LONGER_NEEDED = "no_longer_needed"  # art. 17(1)(a)
    CONSENT_WITHDRAWN = "consent_withdrawn"  # art. 17(1)(b)
    LEGAL_OBLIGATION = "legal_obligation"  # art. 17(1)(e)


class Step(IntEnum):
    """The job's steps, in the order that is the contract (ADR-052 §3)."""

    RECHECK = 0  # hold, last admin, approval still valid, report, ports
    FREEZE = 1  # disabled, no sign-in, sessions ended, keys revoked, links cleared
    MAIL = 2  # app.shared.mail.forget_recipient while the address still exists
    KEYCLOAK = 3  # membership removed; the account deleted when no other tenant has it
    PORTS = 4  # every module's PersonData port, in registry order
    PERSON_ROW = 5  # the users row anonymised (D6b)
    AUDIT = 6  # audit.erase_subject
    EVENTS = 7  # user.status_changed (reason erasure), then person_erasure.completed


LAST_STEP = len(Step)  # 8: every step done

# A request not approved within this is expired (ADR-052 §1).
REQUEST_LIFETIME = timedelta(days=7)
# Text limits, as the table's checks.
REASON_TEXT_MAX = 1000
KEEP_REASON_MAX = 500
KEEP_FILES_MAX = 200

# Problem codes (errors.<code> labels; tests/test_error_labels.py reads PROBLEM_CODES).
ERASE_SELF = "erasure_of_self"
BREAK_GLASS = "erasure_break_glass_account"
HELD = "person_on_legal_hold"
ALREADY_OPEN = "erasure_already_open"
EXPIRED = "erasure_request_expired"
REPORT_UNAVAILABLE = "erasure_report_unavailable"
SAME_APPROVER = "erasure_needs_another_admin"
NOT_PENDING = "erasure_not_pending"
NOT_FOUND = "erasure_not_found"
ALREADY_ERASED = "person_already_erased"
LAST_ADMIN = "last_tenant_admin"  # the existing code of roles.guard_last_admin
ERASE_RIGHT = "people.erase"
PORT_MISSING = "erasure_port_missing"
PORT_KIND_UNDECLARED = "erasure_port_kind_undeclared"
APPROVAL_INVALID = "erasure_approval_invalid"
IDENTITY_UNAVAILABLE = "erasure_identity_unavailable"
SESSIONS_UNAVAILABLE = "erasure_sessions_unavailable"
STEP_FAILED = "erasure_step_failed"
HOLD_NOT_SET = "legal_hold_not_set"
# S1b (D-171 a): the mentions report.
REPORT_NOT_REVIEWED = "erasure_report_not_reviewed"
MENTION_NOT_FOUND = "erasure_mention_not_found"
MENTION_PORT_MISSING = "erasure_mention_port_missing"
# D-171: redacted originals are not kept. While signed history (rows a fingerprinted audit entry
# commits to, ADR-046) cannot be redacted yet, an erasure with such a row kept is never approved
# or run (the coordinator, 2026-11-14).
SIGNED_HISTORY_KEPT = "erasure_signed_history_kept"
# Until directory sync skips erased people (#507), an erasure is never approved: the next LDAP or
# Entra sync would write the person's name and address back (the coordinator, 2026-11-14).
DIRECTORY_SYNC_UNSAFE = "erasure_directory_sync_unsafe"
# The marker would make the field longer than it may be: refused, never cut (lane A, #506).
REDACTION_TOO_LONG = "erasure_redaction_too_long"
REDACTION_HISTORY_REASON = "erasure_redaction"  # the history reason code of a redaction

# Codes a run stops on for good (state failed), as opposed to a passing failure it retries.
REFUSALS: frozenset[str] = frozenset(
    {
        ERASE_SELF,
        BREAK_GLASS,
        HELD,
        LAST_ADMIN,
        REPORT_UNAVAILABLE,
        PORT_MISSING,
        PORT_KIND_UNDECLARED,
        APPROVAL_INVALID,
        SIGNED_HISTORY_KEPT,
    }
)
# Every code an erasure row's last_error_code can hold (`errors.<code>` labels too).
ERROR_CODES: frozenset[str] = REFUSALS | {
    IDENTITY_UNAVAILABLE,
    SESSIONS_UNAVAILABLE,
    STEP_FAILED,
}
PROBLEM_CODES: frozenset[str] = ERROR_CODES | {
    ALREADY_OPEN,
    EXPIRED,
    SAME_APPROVER,
    NOT_PENDING,
    NOT_FOUND,
    ALREADY_ERASED,
    HOLD_NOT_SET,
    REPORT_NOT_REVIEWED,
    MENTION_NOT_FOUND,
    MENTION_PORT_MISSING,
    REDACTION_TOO_LONG,
    DIRECTORY_SYNC_UNSAFE,
}
# Field problem codes of the request body (errors.field.<code> labels).
FIELD_PROBLEMS = frozenset(
    {
        "erasure_confirm_name_mismatch",
        "erasure_successor_not_active",
        "erasure_successor_is_person",
        "erasure_keep_file_unknown",
        "erasure_keep_reason_required",
        "erasure_keep_files_too_many",
    }
)

# Retries of a passing failure (Keycloak or the session store down): the backoff doubles from
# RETRY_FIRST up to RETRY_MAX; after MAX_ATTEMPTS the erasure is failed and admins must look.
RETRY_FIRST = timedelta(seconds=30)
RETRY_MAX = timedelta(hours=1)
MAX_ATTEMPTS = 50

ERASED_PREFIX = "Erased person"
CODE_LENGTH = 4
_CODE_SALT = b"supportx:person-erasure:display-code:v1"


def erased_code(person_id: uuid.UUID) -> str:
    """D6b: a stable 4-character code shown in "Erased person <code>".

    The first four base32 characters of SHA-256 over a fixed context and the person's ID. It is
    derived only from the random record ID (UUIDv7), never from a name, address or anything
    personal, and a hash cannot be turned back into its input: the code identifies the erased
    row among others on screen and reveals nothing about who it was. Two erased people may share
    a code (32^4 = 1,048,576 values); the ID stays the identity.
    """
    digest = hashlib.sha256(_CODE_SALT + person_id.bytes).digest()
    return base64.b32encode(digest).decode("ascii")[:CODE_LENGTH]


def erased_name(person_id: uuid.UUID) -> str:
    """The erased person's display name (data, the same in every language, like any name)."""
    return f"{ERASED_PREFIX} {erased_code(person_id)}"


def erased_email(person_id: uuid.UUID) -> str:
    """An address that can never receive mail (`.invalid`, RFC 2606) and stays unique."""
    return f"erased-{person_id}@invalid"


def expires_at(requested_at: datetime) -> datetime:
    """When an unapproved request lapses."""
    return requested_at + REQUEST_LIFETIME


def is_expired(requested_at: datetime, now: datetime) -> bool:
    """Whether a request made then has lapsed by now."""
    return now >= expires_at(requested_at)


def retry_delay(attempts: int) -> timedelta:
    """Backoff after `attempts` failed runs: 30 s, 60 s, 120 s ... at most an hour."""
    if attempts <= 0:
        return timedelta(0)
    seconds = RETRY_FIRST.total_seconds() * (2 ** min(attempts - 1, 20))
    return min(timedelta(seconds=seconds), RETRY_MAX)


@dataclass(frozen=True)
class Transition:
    """A requested move of an erasure, checked against its state."""

    allowed: bool
    code: str | None = None


_MOVES: dict[str, frozenset[ErasureState]] = {
    "approve": frozenset({ErasureState.REQUESTED}),
    "review": frozenset({ErasureState.REQUESTED}),
    # Redaction (S1b): before the job starts, while the approver still decides or has decided.
    "redact": frozenset({ErasureState.REQUESTED, ErasureState.APPROVED}),
    "reject": frozenset({ErasureState.REQUESTED, ErasureState.APPROVED}),
    "expire": frozenset({ErasureState.REQUESTED}),
    "start": RUNNABLE_STATES,
}


def can(move: str, state: ErasureState) -> Transition:
    """Whether `move` (approve, review, redact, reject, expire, start) may happen in `state`."""
    allowed = state in _MOVES[move]
    return Transition(allowed, None if allowed else NOT_PENDING)


def is_open(state: ErasureState) -> bool:
    """Whether the erasure still blocks a new one for the same person."""
    return state in OPEN_STATES


def same_name(typed: str, display_name: str) -> bool:
    """The typed confirmation matches the person's display name (trimmed, case-insensitive)."""
    return " ".join(typed.split()).casefold() == " ".join(display_name.split()).casefold()
