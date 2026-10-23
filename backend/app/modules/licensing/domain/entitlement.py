"""The entitlement of one tenant and the rules that derive its state: pure Python (WP-009).

An `Entitlement` is what a provider reads (a subscription row, a licence file): edition,
features, counted limits and term. Its *state* is not stored anywhere; it is derived from the term
and the current time on every check (architecture.md §13.6), so a licence moves from active to
grace to read_only on time without any job or event:

    active     inside the term
    grace      expired, or a licence check failing (WP-013: fingerprint mismatch), for at most
               `grace_days`; everything works, admins see a warning
    read_only  after grace, or the subscription is suspended: reads and exports work, writes are
               refused; data is never hidden or deleted
    invalid    no subscription/licence at all, or not valid yet: no features, no writes
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from app.modules.licensing.domain.catalogue import (
    EDITION_DEFAULT_LIMITS,
    EDITION_FEATURES,
    Edition,
    Feature,
    LimitKey,
)

DEFAULT_GRACE_DAYS = 14  # architecture.md §13.6


class EntitlementState(StrEnum):
    """Derived licence state (see module docstring)."""

    ACTIVE = "active"
    GRACE = "grace"
    READ_ONLY = "read_only"
    INVALID = "invalid"


class StateReason(StrEnum):
    """Why the state is not plain `active`. Shown to admins through labels."""

    EXPIRED = "expired"
    LICENCE_MISMATCH = "licence_mismatch"
    SUSPENDED = "suspended"
    NOT_YET_VALID = "not_yet_valid"
    NO_ENTITLEMENT = "no_entitlement"


WRITABLE_STATES = frozenset({EntitlementState.ACTIVE, EntitlementState.GRACE})


@dataclass(frozen=True)
class Term:
    """When the entitlement is valid. `expires_at=None` = open-ended (e.g. auto-renewing plan)."""

    starts_at: datetime
    expires_at: datetime | None = None
    maintenance_until: datetime | None = None
    grace_days: int = DEFAULT_GRACE_DAYS


@dataclass(frozen=True)
class Status:
    """The state at one moment, with its reason and when the grace period ends."""

    state: EntitlementState
    reason: StateReason | None = None
    grace_ends_at: datetime | None = None

    @property
    def allows_writes(self) -> bool:
        """Whether changes are allowed (active or grace)."""
        return self.state in WRITABLE_STATES


@dataclass(frozen=True)
class LimitCheck:
    """Result of checking a counted limit: whether `adding` more fit next to `used`."""

    key: LimitKey
    limit: int | None
    used: int
    adding: int

    @property
    def allowed(self) -> bool:
        """Unlimited, or still within the limit after adding."""
        return self.limit is None or self.used + self.adding <= self.limit

    @property
    def remaining(self) -> int | None:
        """How many more fit (never negative); None = unlimited."""
        return None if self.limit is None else max(0, self.limit - self.used)


@dataclass(frozen=True)
class Entitlement:
    """One tenant's edition, effective features, effective limits and term."""

    edition: Edition | None
    features: frozenset[Feature]
    limits: Mapping[LimitKey, int | None]
    term: Term | None
    suspended: bool = False
    # WP-013 sets this when a licence check (fingerprint, clock) starts failing; the grace period
    # then runs from this moment even though the term has not expired.
    degraded_since: datetime | None = None
    extra_features: frozenset[Feature] = field(default_factory=frozenset)
    limit_overrides: Mapping[LimitKey, int | None] = field(
        default_factory=lambda: MappingProxyType({})
    )

    @classmethod
    def build(  # noqa: PLR0913 - keyword-only, mirrors the licence document fields
        cls,
        edition: Edition,
        *,
        term: Term,
        extra_features: frozenset[Feature] = frozenset(),
        limit_overrides: Mapping[LimitKey, int | None] | None = None,
        suspended: bool = False,
        degraded_since: datetime | None = None,
    ) -> "Entitlement":
        """Edition defaults plus add-on features and limit overrides."""
        overrides = dict(limit_overrides or {})
        limits = {**EDITION_DEFAULT_LIMITS[edition], **overrides}
        return cls(
            edition=edition,
            features=EDITION_FEATURES[edition] | extra_features,
            limits=MappingProxyType(limits),
            term=term,
            suspended=suspended,
            degraded_since=degraded_since,
            extra_features=extra_features,
            limit_overrides=MappingProxyType(overrides),
        )

    @classmethod
    def none(cls) -> "Entitlement":
        """No subscription or licence: nothing is licensed (fail closed)."""
        return cls(
            edition=None,
            features=frozenset(),
            limits=MappingProxyType(dict.fromkeys(LimitKey, 0)),
            term=None,
        )

    def has_feature(self, feature: Feature | str) -> bool:
        """Whether the feature is licensed.

        Independent of the state: in read-only mode licensed modules stay readable (data is never
        hidden, §13.6); only writes stop.
        """
        return feature in self.features

    def limit(self, key: LimitKey) -> int | None:
        """The effective limit (None = unlimited)."""
        return self.limits.get(key, 0)

    def check(self, key: LimitKey, *, used: int, adding: int = 1) -> LimitCheck:
        """Whether `adding` more fit next to `used` existing ones."""
        return LimitCheck(key=key, limit=self.limit(key), used=used, adding=adding)

    def status(self, now: datetime) -> Status:
        """The state at `now` (see module docstring for the rules)."""
        if self.term is None or self.edition is None:
            return Status(EntitlementState.INVALID, StateReason.NO_ENTITLEMENT)
        if now < self.term.starts_at:
            return Status(EntitlementState.INVALID, StateReason.NOT_YET_VALID)
        if self.suspended:
            return Status(EntitlementState.READ_ONLY, StateReason.SUSPENDED)
        problems: list[tuple[datetime, StateReason]] = []
        if self.term.expires_at is not None:
            problems.append((self.term.expires_at, StateReason.EXPIRED))
        if self.degraded_since is not None:
            problems.append((self.degraded_since, StateReason.LICENCE_MISMATCH))
        due = [problem for problem in problems if problem[0] <= now]
        if not due:
            return Status(EntitlementState.ACTIVE)
        since, reason = min(due)
        grace_ends_at = since + timedelta(days=self.term.grace_days)
        if now < grace_ends_at:
            return Status(EntitlementState.GRACE, reason, grace_ends_at)
        return Status(EntitlementState.READ_ONLY, reason, grace_ends_at)

    def upgrade_allowed(self, release_date: datetime) -> bool:
        """Whether a release from `release_date` may be installed (maintenance_until, §13.5)."""
        if self.term is None:
            return False
        return self.term.maintenance_until is None or release_date <= self.term.maintenance_until

    # --- serialisation for the cache (JSON-safe, round-trips exactly) ----------------------------

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form. Stores the inputs (edition, add-ons, overrides), not derived values."""
        term = self.term
        return {
            "edition": self.edition.value if self.edition else None,
            "extra_features": sorted(f.value for f in self.extra_features),
            "limit_overrides": {k.value: v for k, v in self.limit_overrides.items()},
            "suspended": self.suspended,
            "degraded_since": _iso(self.degraded_since),
            "term": None
            if term is None
            else {
                "starts_at": _iso(term.starts_at),
                "expires_at": _iso(term.expires_at),
                "maintenance_until": _iso(term.maintenance_until),
                "grace_days": term.grace_days,
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Entitlement":
        """Inverse of `to_dict`."""
        term = data.get("term")
        starts_at = _parse(term.get("starts_at")) if term else None
        if data.get("edition") is None or term is None or starts_at is None:
            return cls.none()
        return cls.build(
            Edition(data["edition"]),
            term=Term(
                starts_at=starts_at,
                expires_at=_parse(term["expires_at"]),
                maintenance_until=_parse(term["maintenance_until"]),
                grace_days=int(term["grace_days"]),
            ),
            extra_features=frozenset(Feature(f) for f in data.get("extra_features", ())),
            limit_overrides={
                LimitKey(k): v for k, v in dict(data.get("limit_overrides", {})).items()
            },
            suspended=bool(data.get("suspended", False)),
            degraded_since=_parse(data.get("degraded_since")),
        )


def days_left(status: Status, now: datetime) -> int | None:
    """Whole days (rounded up) until the grace period ends, for the admin warning."""
    if status.grace_ends_at is None or status.state is not EntitlementState.GRACE:
        return None
    return max(0, math.ceil((status.grace_ends_at - now) / timedelta(days=1)))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
