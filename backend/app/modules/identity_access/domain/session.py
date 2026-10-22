"""BFF session model and its expiry rules: pure Python (WP-006).

The session record lives server-side only (Valkey, encrypted). The browser holds nothing but an
opaque random ID in an HttpOnly cookie.
"""

import uuid
from dataclasses import asdict, dataclass, field, replace
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

    def expiry(self, now: datetime, *, idle: timedelta, absolute: timedelta) -> ExpiryReason | None:
        """Whether the session has expired at `now`, and why."""
        if now - self.created_at >= absolute:
            return ExpiryReason.ABSOLUTE
        if now - self.last_seen_at >= idle:
            return ExpiryReason.IDLE
        return None

    def ttl(self, now: datetime, *, idle: timedelta, absolute: timedelta) -> timedelta:
        """How long the store should keep the record: the earlier of both deadlines."""
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
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":
        """Inverse of `to_dict`."""
        values = dict(data)
        for key in ("created_at", "last_seen_at", "access_expires_at"):
            values[key] = datetime.fromisoformat(values[key])
        values["tenants"] = [TenantChoice(**t) for t in values["tenants"]]
        return cls(**values)
