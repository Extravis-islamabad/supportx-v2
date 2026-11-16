"""A person's signed-in sessions as the API shows them (ADR-044 item 5).

Shared by the person's own list (the BFF, `/auth/sessions`) and the admin's
(`/people/{id}/sessions`).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.identity_access.domain.place import Place
from app.modules.identity_access.service.auth import ListedSession


class PlaceOut(BaseModel):
    """An approximate place (D-170): a mapped site, the internal network, or a city and country."""

    kind: Literal["site", "internal", "geo"]
    site_id: uuid.UUID | None = Field(default=None, description="kind site: the mapped site.")
    city: str | None = Field(default=None, description="kind geo: the database's English name.")
    country: str | None = Field(default=None, description="kind geo: ISO 3166-1 alpha-2.")

    @classmethod
    def of(cls, stored: object) -> "PlaceOut | None":
        """The API form of a stored place; None for none or a damaged one."""
        place = Place.from_dict(stored)
        if place is None:
            return None
        return cls(kind=place.kind, site_id=place.site_id, city=place.city, country=place.country)


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
    place: PlaceOut | None = Field(
        default=None,
        description="Where it signed in from, approximately (its owner and tenant admins only).",
    )


def listed_out(rows: list[ListedSession], *, show_where: bool = True) -> list[ListedSessionOut]:
    """The API shape of the listed sessions, in the order given.

    `show_where`: the address, device and place (REQ-SEC-030), for the session's owner and tenant
    admins only (lane B); anyone else who may manage people sees when, never where.
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
            place=PlaceOut.of(r.place) if show_where else None,
        )
        for r in rows
    ]
