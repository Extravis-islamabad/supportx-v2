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


def listed_out(rows: list[ListedSession]) -> list[ListedSessionOut]:
    """The API shape of the listed sessions, in the order given."""
    return [
        ListedSessionOut(
            id=r.id,
            client=r.client,
            platform=r.platform,
            app_version=r.app_version,
            started_at=r.started_at,
            last_used_at=r.last_used_at,
            current=r.current,
        )
        for r in rows
    ]
