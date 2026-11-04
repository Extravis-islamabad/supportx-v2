"""Issuing, reading and using action links (WP-030 s3; REQ-NTF-024). See domain.py for the rules.

A module that offers an action registers a handler for it (`register_handler`):

- `version_of(session, object_id)`: the object's version now, or None when it is gone, so a
  link to an object that changed since it was sent is refused as stale;
- `summary(session, subject, object_id)`: what the confirmation page may show (IDs and plain
  fields the recipient may see; never more than the API would give them);
- `act(session, subject, object_id, body)`: the action itself, with the module's own policy
  checks run again now (condition 5). It raises the module's usual errors.

The service only finds the link by its token's digest, checks the link's own state, and marks
it used in the same transaction as the action, so a link never acts twice (the row is locked).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PermissionDenied
from app.shared.action_links import domain as rules
from app.shared.action_links.infra.models import ActionLink
from app.shared.clock import Clock, system_clock


class Actor(Protocol):
    """Who is using the link: the signed-in person (the interim default, plan D7)."""

    @property
    def user_id(self) -> uuid.UUID:
        """The person's ID."""
        ...


class ActionHandler(Protocol):
    """One action a link may take (registered by the module that owns it).

    `subject` is the owning module's own Subject (Any here: the shared package cannot name it).
    """

    async def version_of(self, session: AsyncSession, object_id: uuid.UUID) -> int | None:
        """The object's version now; None when it is gone."""
        ...

    async def summary(
        self,
        session: AsyncSession,
        subject: Any,  # noqa: ANN401 - the module's own Subject
        object_id: uuid.UUID,
    ) -> Mapping[str, Any]:
        """What the confirmation page may show this person."""
        ...

    async def act(
        self,
        session: AsyncSession,
        subject: Any,  # noqa: ANN401 - the module's own Subject
        object_id: uuid.UUID,
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """The action, with the module's policy checks run again now."""
        ...


_HANDLERS: dict[str, ActionHandler] = {}


def register_handler(action: str, handler: ActionHandler) -> None:
    """Called by the owning module at import (idempotent)."""
    _HANDLERS[action] = handler


@dataclass(frozen=True)
class Opened:
    """A link that may act now: what it does, on what, and what the page may show."""

    action: str
    object_type: str
    object_id: uuid.UUID
    expires_at: datetime
    summary: Mapping[str, Any]


class LinkRefused(Conflict):
    """The link does nothing now: its `code` says why (domain.Refusal); audited by the route."""


def _refuse(reason: rules.Refusal) -> Exception:
    if reason is rules.Refusal.NOT_FOUND:
        return NotFound(code=reason.value)
    if reason is rules.Refusal.WRONG_RECIPIENT:
        return PermissionDenied(code=reason.value)
    return LinkRefused(code=reason.value)


async def issue(  # noqa: PLR0913 - every binding of the link, explicit
    session: AsyncSession,
    *,
    recipient_id: uuid.UUID,
    action: str,
    object_type: str,
    object_id: uuid.UUID,
    object_version: int,
    ttl: timedelta = rules.DEFAULT_TTL,
    clock: Clock = system_clock,
) -> str:
    """A new link's token, for the message only; the table keeps its digest."""
    if action not in _HANDLERS:
        msg = f"no handler for action {action!r}"
        raise ValueError(msg)
    token = rules.new_token()
    session.add(
        ActionLink(
            tenant_id=_tenant(session),
            token_digest=token.digest,
            recipient_id=recipient_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            object_version=object_version,
            expires_at=rules.expiry(clock.now(), ttl),
        )
    )
    await session.flush()
    return token.secret


def _tenant(session: AsyncSession) -> uuid.UUID:
    from app.core.database import SESSION_TENANT_KEY  # noqa: PLC0415 - core imports shared

    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant


async def _find(session: AsyncSession, secret: str, *, lock: bool) -> ActionLink | None:
    if not rules.well_formed(secret):
        return None
    query = select(ActionLink).where(
        ActionLink.token_digest == rules.digest_of(secret), ActionLink.deleted_at.is_(None)
    )
    found: ActionLink | None = await session.scalar(query.with_for_update() if lock else query)
    return found


async def _checked(
    session: AsyncSession, secret: str, actor: Actor, *, lock: bool, clock: Clock
) -> tuple[ActionLink, ActionHandler]:
    link = await _find(session, secret, lock=lock)
    handler = _HANDLERS.get(link.action) if link is not None else None
    if link is None or handler is None:
        raise _refuse(rules.Refusal.NOT_FOUND)
    current = await handler.version_of(session, link.object_id)
    state = rules.LinkState(
        recipient_id=link.recipient_id,
        object_version=link.object_version,
        expires_at=link.expires_at,
        used_at=link.used_at,
        revoked_at=link.revoked_at,
    )
    reason = rules.refusal(state, now=clock.now(), actor=actor.user_id, current_version=current)
    if reason is None and current is None:
        reason = rules.Refusal.REVOKED  # the object is gone
    if reason is not None:
        raise _refuse(reason)
    return link, handler


async def peek(
    session: AsyncSession, secret: str, actor: Actor, *, clock: Clock = system_clock
) -> Opened:
    """What the link would do, for its confirmation page (never acts: condition 1)."""
    link, handler = await _checked(session, secret, actor, lock=False, clock=clock)
    return Opened(
        action=link.action,
        object_type=link.object_type,
        object_id=link.object_id,
        expires_at=link.expires_at,
        summary=await handler.summary(session, actor, link.object_id),
    )


async def use(
    session: AsyncSession,
    secret: str,
    actor: Actor,
    body: Mapping[str, Any],
    *,
    clock: Clock = system_clock,
) -> tuple[Opened, Mapping[str, Any]]:
    """Take the link's action once: the row is locked, checked, acted on and marked used."""
    link, handler = await _checked(session, secret, actor, lock=True, clock=clock)
    opened = Opened(
        action=link.action,
        object_type=link.object_type,
        object_id=link.object_id,
        expires_at=link.expires_at,
        summary={},
    )
    result = await handler.act(session, actor, link.object_id, body)
    link.used_at = clock.now()
    link.used_by = actor.user_id
    link.version += 1
    await session.flush()
    return opened, result


async def revoke_for(
    session: AsyncSession, object_type: str, object_id: uuid.UUID, *, clock: Clock = system_clock
) -> int:
    """Every open link to an object stops working (e.g. the request was withdrawn)."""
    done = await session.execute(
        update(ActionLink)
        .where(
            ActionLink.object_type == object_type,
            ActionLink.object_id == object_id,
            ActionLink.used_at.is_(None),
            ActionLink.revoked_at.is_(None),
        )
        .values(revoked_at=clock.now(), version=ActionLink.version + 1)
    )
    return int(getattr(done, "rowcount", 0) or 0)


__all__ = [
    "ActionHandler",
    "Actor",
    "LinkRefused",
    "Opened",
    "issue",
    "peek",
    "register_handler",
    "revoke_for",
    "use",
]
