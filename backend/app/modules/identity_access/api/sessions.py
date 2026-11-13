"""A person's signed-in sessions as the API shows them (ADR-044 item 5).

Shared by the person's own list (the BFF, `/auth/sessions`) and the admin's
(`/people/{id}/sessions`).
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.identity_access.service.auth import ListedSession


class ListedSessionOut(BaseModel):
    """One of your sessions (ADR-044 item 5): where and when, never its secret id."""

    id: str = Field(description="The session's listed id (not usable to sign in).")
    client: str = Field(description="console, portal or mobile")
    platform: str | None = Field(description="ios or android for the mobile app")
    app_version: str | None
    started_at: datetime | None
    last_used_at: datetime | None
    current: bool = Field(description="This browser or device.")
    ip: str | None = Field(
        default=None,
        description="The address it signed in from (its owner and tenant admins only).",
    )
    device: str | None = Field(
        default=None,
        description="browser:system codes, e.g. chrome:windows (labelled `device.*`), or null.",
    )


def listed_out(rows: list[ListedSession], *, show_where: bool = True) -> list[ListedSessionOut]:
    """The API shape of the listed sessions, in the order given.

    `show_where`: the address and device (REQ-SEC-030), for the session's owner and tenant admins
    only (lane B); anyone else who may manage people sees when, never where.
    """
    return [
        ListedSessionOut(
            id=r.id,
            client=r.client,
            platform=r.platform,
            app_version=r.app_version,
            started_at=r.started_at,
            last_used_at=r.last_used_at,
            current=r.current,
            ip=r.ip if show_where else None,
            device=r.device if show_where else None,
        )
        for r in rows
    ]
