"""Approval delegation and restarting approval (WP-047a S3b; REQ-SR-035, REQ-SR-041). Pure, no I/O.

Delegation (035): an approver names a delegate for a date range, for example while on leave. New
request approvals for them in that range go to the delegate; the approver can still act. The
coordinator's condition 1: the delegate is never the delegator, and both dates are set with a
capped length (`MAX_DAYS`). One delegator has at most one delegation at a time (no overlaps), and
a delegate's own delegation is never followed (no chains: that is the service's routing rule).

Restart (041): when an answer the item marks as "restarts approval" changes (or the quantity or
the requested-for person, when the item says so), approval starts again from its first stage in
a new round. `restart_keys` says which of the marked keys changed.
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

MAX_DAYS = 90  # the coordinator's cap: a delegation is for a leave, never for good
REASON_MAX = 500
QUANTITY = "quantity"  # restart keys for the request's own values, next to its answers' keys
REQUESTED_FOR = "requested_for"

FIELD_PROBLEMS = frozenset(
    {
        "delegate_is_delegator",
        "end_before_start",
        "delegation_too_long",
        "delegation_overlaps",
        "delegation_ended",
        "delegate_not_eligible",
        "delegation_reason_too_long",
    }
)


class DelegationEnd(StrEnum):
    """Why a delegation is over (its history and notices)."""

    EXPIRED = "expired"  # its end came
    ENDED = "ended"  # ended early by the delegator or an administrator


@dataclass(frozen=True)
class Window:
    """A delegation's dates: active from `starts_at` until `ends_at` (or `ended_at`, if earlier)."""

    starts_at: datetime
    ends_at: datetime
    ended_at: datetime | None = None

    @property
    def until(self) -> datetime:
        """The moment it stops."""
        return self.ends_at if self.ended_at is None else min(self.ends_at, self.ended_at)

    def active_at(self, now: datetime) -> bool:
        """Whether it routes approvals at `now`."""
        return self.starts_at <= now < self.until


def problems(
    delegator_id: uuid.UUID,
    delegate_id: uuid.UUID,
    window: Window,
    *,
    reason: str | None = None,
) -> list[tuple[str, str]]:
    """Field problems of a delegation's own values (condition 1)."""
    found: list[tuple[str, str]] = []
    if delegate_id == delegator_id:
        found.append(("delegate_id", "delegate_is_delegator"))
    if window.ends_at <= window.starts_at:
        found.append(("ends_at", "end_before_start"))
    elif window.ends_at - window.starts_at > timedelta(days=MAX_DAYS):
        found.append(("ends_at", "delegation_too_long"))
    if reason is not None and len(reason.strip()) > REASON_MAX:
        found.append(("reason", "delegation_reason_too_long"))
    return found


def overlaps(window: Window, others: Iterable[Window]) -> bool:
    """Whether `window` shares any moment with another of the same delegator's delegations."""
    return any(window.starts_at < o.until and o.starts_at < window.until for o in others)


def restart_keys(  # noqa: PLR0913 - what was, what is, and what counts, explicit
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    marked: Iterable[str],
    *,
    quantity: tuple[int | None, int | None] = (None, None),
    requested_for: tuple[uuid.UUID | None, uuid.UUID | None] = (None, None),
    on_quantity: bool = False,
    on_requested_for: bool = False,
) -> list[str]:
    """The marked keys whose value changed, in a stable order (041 AC1, AC2).

    An answer key counts when the item marks its question "restarts approval"; the quantity and
    the requested-for person count when the item says so. An unmarked change restarts nothing.
    """
    changed = sorted(k for k in set(marked) if before.get(k) != after.get(k))
    if on_quantity and quantity[0] != quantity[1]:
        changed.append(QUANTITY)
    if on_requested_for and requested_for[0] != requested_for[1]:
        changed.append(REQUESTED_FOR)
    return changed


def current_round(rounds: Sequence[int]) -> int:
    """The round the engine counts: the latest one (earlier rounds stay in history only)."""
    return max(rounds, default=1)
