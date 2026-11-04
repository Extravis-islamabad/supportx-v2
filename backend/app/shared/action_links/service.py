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
    `feature`: the licence feature the action belongs to; the routes without sign-in ask the
    entitlement gate for it (and refuse writes in read-only mode), as a module's router would.
    """

    feature: str

    async def version_of(self, session: AsyncSession, object_id: uuid.UUID) -> int | None:
        """The object's version now; None when it is gone or no longer waits."""
        ...

    async def sign_in_required(self, session: AsyncSession) -> bool:
        """Whether the tenant wants the recipient signed in to use this action (D-132)."""
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
    if reason is rules.Refusal.SIGN_IN_REQUIRED:
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


def _digest(secret: str) -> bytes | None:
    return rules.digest_of(secret) if rules.well_formed(secret) else None


async def _find(session: AsyncSession, secret: str) -> ActionLink | None:
    digest = _digest(secret)
    if digest is None:
        return None
    found: ActionLink | None = await session.scalar(
        select(ActionLink).where(ActionLink.token_digest == digest, ActionLink.deleted_at.is_(None))
    )
    return found


def _state(link: ActionLink) -> rules.LinkState:
    return rules.LinkState(
        recipient_id=link.recipient_id,
        object_version=link.object_version,
        expires_at=link.expires_at,
        used_at=link.used_at,
        revoked_at=link.revoked_at,
    )


async def _checked(
    session: AsyncSession, link: ActionLink | None, actor: uuid.UUID | None, *, clock: Clock
) -> tuple[ActionLink, ActionHandler]:
    handler = _HANDLERS.get(link.action) if link is not None else None
    if link is None or handler is None:
        raise _refuse(rules.Refusal.NOT_FOUND)
    current = await handler.version_of(session, link.object_id)
    reason = rules.refusal(_state(link), now=clock.now(), actor=actor, current_version=current)
    if reason is not None:
        raise _refuse(reason)
    return link, handler


async def recipient_of(
    session: AsyncSession, secret: str, *, clock: Clock = system_clock
) -> tuple[uuid.UUID, str]:
    """Who a link is for and its action's feature, for the no-sign-in session (D-132).

    Changes nothing. With the tenant asking for a signed-in approver, 403
    `action_link_sign_in_required`: the page sends the person to sign in instead.
    """
    link, handler = await _checked(session, await _find(session, secret), None, clock=clock)
    if await handler.sign_in_required(session):
        raise _refuse(rules.Refusal.SIGN_IN_REQUIRED)
    return link.recipient_id, handler.feature


async def peek(
    session: AsyncSession, secret: str, actor: Actor, *, clock: Clock = system_clock
) -> Opened:
    """What the link would do, for its confirmation page (never acts: condition 1)."""
    link, handler = await _checked(
        session, await _find(session, secret), actor.user_id, clock=clock
    )
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
    """Take the link's action once (lane B review: an atomic UPDATE, never read-then-write).

    The row is marked used by one statement that also requires it to be unused, unrevoked,
    unexpired and the actor's; a second request waits on that row and then finds it used. A
    refusal (the approval decided elsewhere, the approver changed) rolls the mark back and
    answers in words; an action that fails rolls it back too, so the link is never half-used.
    """
    digest = _digest(secret)
    now = clock.now()
    claimed: ActionLink | None = None
    if digest is not None:
        claimed = await session.scalar(
            update(ActionLink)
            .where(
                ActionLink.token_digest == digest,
                ActionLink.used_at.is_(None),
                ActionLink.revoked_at.is_(None),
                ActionLink.expires_at > now,
                ActionLink.deleted_at.is_(None),
                ActionLink.recipient_id == actor.user_id,
            )
            .values(used_at=now, used_by=actor.user_id, version=ActionLink.version + 1)
            .returning(ActionLink)
            .execution_options(synchronize_session=False)
        )
    if claimed is None:  # say why, from the row as it is (or 404 when it is not theirs)
        await _checked(session, await _find(session, secret), actor.user_id, clock=clock)
        raise _refuse(rules.Refusal.NOT_FOUND)  # pragma: no cover - _checked always refuses
    handler = _HANDLERS.get(claimed.action)
    if handler is None:  # pragma: no cover - registered at import
        raise _refuse(rules.Refusal.NOT_FOUND)
    if await handler.version_of(session, claimed.object_id) != claimed.object_version:
        raise _refuse(rules.Refusal.REVOKED)  # decided elsewhere, withdrawn, approver changed
    try:
        result = await handler.act(session, actor, claimed.object_id, body)
    except (Conflict, PermissionDenied) as refused:
        if isinstance(refused, LinkRefused):
            raise
        raise _refuse(rules.Refusal.REVOKED) from refused  # no longer theirs to decide
    opened = Opened(
        action=claimed.action,
        object_type=claimed.object_type,
        object_id=claimed.object_id,
        expires_at=claimed.expires_at,
        summary={},
    )
    return opened, result


async def note_failed_use(
    session: AsyncSession, secret: str, *, clock: Clock = system_clock
) -> None:
    """Count a refused use of an existing link; revoke it at the cap (lane B review).

    Run in its own transaction by the route after a refusal, so the count survives the
    refused request's rollback. An unknown token counts nothing (there is nothing to protect).
    """
    digest = _digest(secret)
    if digest is None:
        return
    await session.execute(
        update(ActionLink)
        .where(ActionLink.token_digest == digest, ActionLink.revoked_at.is_(None))
        .values(failed_uses=ActionLink.failed_uses + 1, version=ActionLink.version + 1)
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(ActionLink)
        .where(
            ActionLink.token_digest == digest,
            ActionLink.revoked_at.is_(None),
            ActionLink.failed_uses >= rules.MAX_FAILED_USES,
        )
        .values(revoked_at=clock.now())
        .execution_options(synchronize_session=False)
    )


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
    "note_failed_use",
    "peek",
    "recipient_of",
    "register_handler",
    "revoke_for",
    "use",
]
