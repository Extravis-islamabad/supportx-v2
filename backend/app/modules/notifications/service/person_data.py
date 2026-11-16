"""Notifications' slice of a person's erasure (ADR-052 §4; D-171).

Their in-app entries and delivery rows go and they come off the rules that name them (the same
`forget` as #492's consumer, idempotent, so the job's own step and the later event agree), and
their notification preferences go for good (0166 lets the app delete them). Their e-mails'
content goes with the mail sender's retention purge; nothing here holds it. Counts only.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import ClassVar

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import ErasureBatch, register_person_data
from app.modules.notifications.infra.models import NotificationPreference
from app.modules.notifications.service.erasure import forget


class Notifications:
    """`notifications`: the person's own notification rows (band 500-599)."""

    module: ClassVar[str] = "notifications"
    order: ClassVar[int] = 560
    kinds: ClassVar[frozenset[str]] = frozenset(
        {"deliveries_deleted", "notifications_deleted", "preferences_deleted"}
    )

    async def erase_person(  # noqa: PLR0913 - the port contract
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """All at once: a person's notification rows are few (one call, no cursor)."""
        del successor_id, keep_files, now, cursor  # nothing shared, no files, no batches
        deliveries, entries = await forget(session, person_id)
        preferences = await session.execute(
            delete(NotificationPreference).where(NotificationPreference.user_id == person_id)
        )
        counts = {
            "deliveries_deleted": deliveries,
            "notifications_deleted": entries,
            "preferences_deleted": int(getattr(preferences, "rowcount", 0) or 0),
        }
        return ErasureBatch({k: v for k, v in counts.items() if v})


PORT = Notifications()


def register() -> None:
    """At import (the registry refuses the job while it is missing)."""
    register_person_data(PORT)
