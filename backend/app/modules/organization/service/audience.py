"""Who an audience reaches: counted, or named for those allowed (WP-053 0185, D-172 (3)).

People live in identity_access, which this module never reads: identity_access registers the
resolver at start-up, as it does the site people counter. Each active person counts once, however
many of the audience's refs reach them; disabled, deleted and non-person accounts never count.
Names go only to a reader holding `users.view`, checked here, and never into realtime payloads.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDenied
from app.modules.organization.domain.audience import Audience

USERS_VIEW = "users.view"  # identity_access's right to see people
PEOPLE_MAX = 200  # names in one answer


@dataclass(frozen=True)
class AudienceResolver:
    """How many people an audience reaches, and up to `limit` of them by name."""

    count: Callable[[AsyncSession, Audience], Awaitable[int]]
    people: Callable[[AsyncSession, Audience, int], Awaitable[list[tuple[uuid.UUID, str]]]]


_RESOLVERS: list[AudienceResolver] = []


def register_audience_resolver(resolver: AudienceResolver) -> None:
    """At start-up (identity_access): the one resolver of people."""
    if resolver not in _RESOLVERS:
        _RESOLVERS.append(resolver)


def unregister_audience_resolver(resolver: AudienceResolver) -> None:
    """At shutdown."""
    if resolver in _RESOLVERS:
        _RESOLVERS.remove(resolver)


def _resolver() -> AudienceResolver | None:
    return _RESOLVERS[0] if _RESOLVERS else None


async def count_people(session: AsyncSession, audience: Audience) -> int:
    """How many active people the audience reaches, each once (none registered: nobody)."""
    resolver = _resolver()
    if resolver is None or audience.empty:
        return 0
    return await resolver.count(session, audience)


async def people_in(
    session: AsyncSession,
    subject: Any,  # noqa: ANN401 - identity_access's Subject (this module never imports it)
    audience: Audience,
    *,
    limit: int = PEOPLE_MAX,
) -> list[tuple[uuid.UUID, str]]:
    """Up to `limit` of the audience's people, by name, for a reader holding `users.view`."""
    if not subject.holds(USERS_VIEW):
        raise PermissionDenied(params={"permission": USERS_VIEW})
    resolver = _resolver()
    if resolver is None or audience.empty:
        return []
    return await resolver.people(session, audience, max(1, min(limit, PEOPLE_MAX)))
