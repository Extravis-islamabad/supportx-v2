"""Bookings ahead: the pure rules (WP-049b s1; REQ-AST-032). No I/O.

A booking holds one specific asset for a period. Two bookings, or a booking and the asset's
open loan, never share a moment (touching ends do not overlap). When the period asked for is
taken, the next free day is suggested: the same length of time, starting a whole number of days
later, clear of everything already held (AC1).
"""

from collections.abc import Iterable
from datetime import datetime, timedelta

from app.modules.assets.domain.loans import Period, any_overlap

BOOKING_STATUSES = ("booked", "handed_over", "cancelled")
BOOKING_LENGTH_MAX = timedelta(days=90)
SEARCH_DAYS = 366  # how far ahead a free day is looked for


def next_free(
    wanted: Period, taken: Iterable[Period], *, days: int = SEARCH_DAYS
) -> datetime | None:
    """The first start, a whole day or more after `wanted`'s, with the same length free.

    None when nothing is free within `days` days.
    """
    held = list(taken)
    length = wanted.due_at - wanted.starts_at
    for step in range(1, days + 1):
        start = wanted.starts_at + timedelta(days=step)
        if not any_overlap(Period(start, start + length), held):
            return start
    return None
