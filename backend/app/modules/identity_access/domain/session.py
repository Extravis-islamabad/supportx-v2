"""BFF session model and its expiry rules: pure Python (WP-006).

The session record lives server-side only (Valkey, encrypted). The browser holds nothing but an
opaque random ID in an HttpOnly cookie.
"""

import uuid
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

REFRESH_MARGIN = timedelta(seconds=30)


class ExpiryReason(StrEnum):
    """Why a session can no longer be used."""

    IDLE = "idle"
    ABSOLUTE = "absolute"


@dataclass(frozen=True)
class TenantChoice:
    """A tenant the user may switch to (from their organization memberships)."""

    tenant_id: str
    name: str


# Left out of the stored record while empty: a session without them reads the same on a pod of
# an earlier release (rolling update, §14.3).
_OPTIONAL_FIELDS = (
    "device_platform",
    "app_version",
    "sign_in_ip",
    "device",
    "auth_time",
    "place",
)


@dataclass(frozen=True)
class Session:
    """Everything the BFF knows about a logged-in browser. Never sent to the browser."""

    subject: str
    user_id: str
    tenant_id: str
    tenant_name: str
    tenants: list[TenantChoice]
    email: str
    display_name: str
    locale: str
    user_type: str
    roles: list[str]
    client: str
    csrf_token: str
    created_at: datetime
    last_seen_at: datetime
    access_expires_at: datetime
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    id_token: str = field(repr=False)
    keycloak_session_id: str | None = None
    # The tenant's limits when the session began (WP-039, REQ-SEC-029); None = the platform's.
    idle_seconds: int | None = None
    absolute_seconds: int | None = None
    # MFA required here but not set up yet (WP-039 session 3): enrol by then (ISO time), else
    # None. The console and portal show a reminder with a button to set it up.
    mfa_due_at: str | None = None
    # The mobile app's sessions only (ADR-044 item 5): ios or android, and the app's version,
    # shown in the person's session list. None for the web apps.
    device_platform: str | None = None
    app_version: str | None = None
    # How the person signed in (WP-057 S1b, lane B's condition 2): from the verified ID token at
    # sign-in, kept for the session, as a tenant switch has no new token and the single sign-on
    # rule must judge the original method. None for sessions begun before S1b (judged unknown).
    sign_in_method: str | None = None
    identity_provider: str | None = None
    # A break-glass admin's password sign-in while single sign-on is required: the sign-in
    # route audits it and alerts the other admins.
    break_glass: bool = False
    # WP-057 S2a (REQ-SEC-030, REQ-SEC-027): the address the BFF saw at sign-in (never updated
    # afterwards), a short device code (domain/sign_in.device: never the raw User-Agent), and
    # when the person last proved who they are (ISO time: sign-in or a confirmation).
    sign_in_ip: str | None = None
    device: str | None = None
    auth_time: str | None = None
    # WP-057 S2b (D-170): the approximate place of sign_in_ip in this tenant (domain/place.py's
    # stored form: a mapped site, the internal network, or a city and country), or None.
    place: dict[str, Any] | None = None

    def limits(self, *, idle: timedelta, absolute: timedelta) -> tuple[timedelta, timedelta]:
        """The (idle, absolute) limits of the session; `idle` and `absolute` when it has none."""
        return (
            idle if self.idle_seconds is None else timedelta(seconds=self.idle_seconds),
            absolute if self.absolute_seconds is None else timedelta(seconds=self.absolute_seconds),
        )

    def expiry(self, now: datetime, *, idle: timedelta, absolute: timedelta) -> ExpiryReason | None:
        """Whether the session has expired at `now`, and why (its own limits first)."""
        idle, absolute = self.limits(idle=idle, absolute=absolute)
        if now - self.created_at >= absolute:
            return ExpiryReason.ABSOLUTE
        if now - self.last_seen_at >= idle:
            return ExpiryReason.IDLE
        return None

    def ttl(self, now: datetime, *, idle: timedelta, absolute: timedelta) -> timedelta:
        """How long the store should keep the record: the earlier of both deadlines."""
        idle, absolute = self.limits(idle=idle, absolute=absolute)
        return min(self.last_seen_at + idle, self.created_at + absolute) - now

    def needs_refresh(self, now: datetime) -> bool:
        """Whether the access token is (about to be) expired."""
        return now >= self.access_expires_at - REFRESH_MARGIN

    def touched(self, now: datetime) -> "Session":
        """The same session, seen at `now`."""
        return replace(self, last_seen_at=now)

    @property
    def tenant_uuid(self) -> uuid.UUID:
        """Active tenant as a UUID."""
        return uuid.UUID(self.tenant_id)

    @property
    def user_uuid(self) -> uuid.UUID:
        """User (in the active tenant) as a UUID."""
        return uuid.UUID(self.user_id)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict (datetimes as ISO strings) for the encrypted store."""
        data = asdict(self)
        for key in ("created_at", "last_seen_at", "access_expires_at"):
            data[key] = getattr(self, key).isoformat()
        for key in _OPTIONAL_FIELDS:
            if data[key] is None:
                del data[key]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":
        """Inverse of `to_dict`."""
        values = dict(data)
        for key in ("created_at", "last_seen_at", "access_expires_at"):
            values[key] = datetime.fromisoformat(values[key])
        values["tenants"] = [TenantChoice(**t) for t in values["tenants"]]
        # Fields a later release added are left out, never a TypeError: during a rolling update
        # this release reads sessions the next one wrote (lane C's S1b finding, #459).
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in values.items() if k in known})
