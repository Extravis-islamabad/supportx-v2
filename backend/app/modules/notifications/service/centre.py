"""The notification centre and personal preferences (REQ-INC-131, REQ-NTF-016).

A person sees only their own entries (the user ID comes from their session, never from the
request), newest first, with the unread count. Reading entries, and changing preferences, is
told to their other devices through their personal channel.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.modules.notifications.domain.rules import Preferences
from app.modules.notifications.events import NotificationsRead, PreferencesChanged
from app.modules.notifications.infra.models import Notification, NotificationPreference
from app.shared.events import record_event
from app.shared.notifications.ports import (
    NotificationCategory,
    NotificationChannel,
    record_sources,
)

PAGE_MAX = 100


@dataclass(frozen=True)
class CentrePage:
    """A page of a person's entries."""

    items: list[Notification]
    next_cursor: uuid.UUID | None
    unread: int


async def unread_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    """The badge number."""
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
        or 0
    )


async def page(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    cursor: uuid.UUID | None = None,
    limit: int = 30,
    unread_only: bool = False,
) -> CentrePage:
    """Newest first; `cursor` is the last ID of the previous page (IDs are time-ordered)."""
    size = max(1, min(limit, PAGE_MAX))
    query = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    if cursor is not None:
        query = query.where(Notification.id < cursor)
    rows = list(await session.scalars(query.order_by(Notification.id.desc()).limit(size + 1)))
    more = len(rows) > size
    items = rows[:size]
    return CentrePage(
        items, items[-1].id if more and items else None, await unread_count(session, user_id)
    )


async def entry(
    session: AsyncSession, user_id: uuid.UUID, notification_id: uuid.UUID
) -> Notification:
    """One of the person's own entries (404 for anyone else's)."""
    found = await session.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
    )
    if found is None:
        raise NotFound(code="notification_not_found")
    return found


async def mark_read(
    session: AsyncSession, user_id: uuid.UUID, notification_ids: Sequence[uuid.UUID] | None
) -> int:
    """Mark the given entries (None: all unread ones) read; how many changed."""
    now = datetime.now(UTC)
    statement = update(Notification).where(
        Notification.user_id == user_id, Notification.read_at.is_(None)
    )
    if notification_ids is not None:
        statement = statement.where(Notification.id.in_(list(notification_ids)))
    result = await session.execute(statement.values(read_at=now, updated_at=now))
    changed = int(getattr(result, "rowcount", 0) or 0)
    if changed:
        await record_event(
            session,
            NotificationsRead(
                user_id=user_id,
                notification_ids=list(notification_ids or []),
                all=notification_ids is None,
            ),
            aggregate_id=user_id,
        )
    return changed


# --- preferences -----------------------------------------------------------------------------


@dataclass(frozen=True)
class PreferenceView:
    """A person's preferences, with what they cannot switch off and why."""

    preferences: Preferences
    version: int  # 0: never saved (the defaults)
    locked: frozenset[str]  # categories with a required event: shown locked, with the reason


def locked_categories() -> frozenset[str]:
    """Categories holding an event people cannot switch off (Appendix A: assigned, mentions)."""
    return frozenset(
        event.category.value
        for source in record_sources()
        for event in source.events
        if event.required
    )


async def preferences(session: AsyncSession, user_id: uuid.UUID) -> PreferenceView:
    """The person's preferences (defaults when never saved)."""
    row = await session.get(NotificationPreference, (session_tenant(session), user_id))
    if row is None:
        return PreferenceView(Preferences(), 0, locked_categories())
    return PreferenceView(
        Preferences(
            off=frozenset((str(c), NotificationChannel(str(ch))) for c, ch in row.off),
            do_not_disturb=row.do_not_disturb,
        ),
        row.version,
        locked_categories(),
    )


def session_tenant(session: AsyncSession) -> uuid.UUID:
    """The tenant of a tenant session (the composite key of preferences starts with it)."""
    from app.core.database import SESSION_TENANT_KEY  # noqa: PLC0415 - one use

    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant


async def save_preferences(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    expected_version: int,
    off: Sequence[tuple[str, str]],
    do_not_disturb: bool,
) -> PreferenceView:
    """Replace the person's preferences (If-Match; 0 for the first save)."""
    categories = {c.value for c in NotificationCategory}
    channels = {c.value for c in NotificationChannel}
    locked = locked_categories()
    problems = [
        FieldError(
            field=f"body.off[{i}]", code="invalid_choice", message_key="errors.field.invalid_choice"
        )
        for i, (category, channel) in enumerate(off)
        if category not in categories or channel not in channels
    ]
    if problems:
        raise ValidationFailed(errors=problems)
    # Required events stay on whatever is sent: their categories are dropped, never refused,
    # so an old screen cannot fail the whole save (REQ-NTF-016 AC2).
    kept = sorted({(c, ch) for c, ch in off if c not in locked})
    tenant = session_tenant(session)
    row = await session.get(NotificationPreference, (tenant, user_id), with_for_update=True)
    current = 0 if row is None else row.version
    if current != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": current},
        )
    if row is None:
        row = NotificationPreference(tenant_id=tenant, user_id=user_id, version=1)
        session.add(row)
    else:
        row.version += 1
        row.updated_at = datetime.now(UTC)
    row.off = [list(pair) for pair in kept]
    row.do_not_disturb = do_not_disturb
    await session.flush()
    await record_event(session, PreferencesChanged(user_id=user_id), aggregate_id=user_id)
    return await preferences(session, user_id)
