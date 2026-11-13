"""A fail-fast circuit breaker for the BFF's back channel to Keycloak (ADR-051).

Per process and in memory on purpose: each API pod finds out on its own that Keycloak does not
answer, and a pod that can reach it again closes its own breaker on the next call. Nothing is
shared, so nothing can stay open after Keycloak is back for longer than one cool-down.

Only unreachability opens it (a connection error, a timeout, a 5xx from Keycloak or the proxy in
front of it). A refusal (400/401, e.g. `invalid_grant`) proves Keycloak answers, so it closes the
breaker instead.
"""

import time
from collections.abc import Callable

COOL_DOWN_SECONDS = 15.0


class CircuitBreaker:
    """Closed → open (fail fast for the cool-down) → one trial call → closed or open again."""

    def __init__(
        self,
        cool_down_s: float = COOL_DOWN_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cool_down_s = cool_down_s
        self._monotonic = monotonic
        self._open_until: float | None = None

    @property
    def is_open(self) -> bool:
        """True while calls must fail without being tried (the cool-down has not run out)."""
        return self._open_until is not None and self._monotonic() < self._open_until

    def allow(self) -> bool:
        """Whether this call may go to Keycloak.

        After the cool-down exactly one caller gets through as the trial (half-open): the
        breaker is pushed out by another cool-down before it goes, so concurrent callers keep
        failing fast instead of all waiting on a Keycloak that may still be gone. The trial's
        outcome then closes the breaker or keeps it open.
        """
        if self._open_until is None:
            return True
        now = self._monotonic()
        if now < self._open_until:
            return False
        self._open_until = now + self._cool_down_s
        return True

    def succeeded(self) -> None:
        """Keycloak answered (even with a refusal): close the breaker."""
        self._open_until = None

    def failed(self) -> None:
        """Keycloak could not be reached: fail fast for the cool-down."""
        self._open_until = self._monotonic() + self._cool_down_s
