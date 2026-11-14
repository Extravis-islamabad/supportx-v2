"""Integrations' slice of a person's erasure (ADR-052 §4; D-171; lane B's answer 5).

- Mail they sent: the ledger row stays (its counts and outcome), but the sender becomes the
  reserved marker and the subject too, and the raw message goes (it would otherwise wait for the
  quarantine's expiry). In bounded batches, by address.
- A block rule naming their address as the sender comes off (soft-deleted, as an admin's
  removal), so their address is held nowhere.

The directory link (directory_people, WP-040's sync) is the directory module's, not here.
Counts only.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import ClassVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import (
    ERASE_BATCH,
    ErasureBatch,
    register_person_data,
    user_contacts,
)
from app.modules.integrations.infra.models import MailBlockRule, MailFetched
from app.shared.erasure import ERASED_ON_REQUEST


class Integrations:
    """`integrations`: the mail they sent and block rules naming them (band 500-599)."""

    module: ClassVar[str] = "integrations"
    order: ClassVar[int] = 570
    kinds: ClassVar[frozenset[str]] = frozenset({"mail_cleared", "block_rules_removed"})

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
        """One batch of their mail; the block rules with the first call."""
        del successor_id, keep_files, cursor  # by address: cleared rows no longer match
        key = str(person_id)
        contact = (await user_contacts(session, [key])).get(key)
        email = contact[1] if contact else None
        if not email:
            return ErasureBatch({})
        address = email.casefold()
        counts: dict[str, int] = {}
        rules = list(
            await session.scalars(
                select(MailBlockRule)
                .where(
                    MailBlockRule.kind == "sender",
                    func.lower(MailBlockRule.value) == address,
                    MailBlockRule.deleted_at.is_(None),
                )
                .with_for_update()
            )
        )
        for rule in rules:
            rule.deleted_at = now
            rule.version += 1
        if rules:
            counts["block_rules_removed"] = len(rules)
        mail = list(
            await session.scalars(
                select(MailFetched)
                .where(func.lower(MailFetched.sender) == address)
                .limit(ERASE_BATCH)
                .with_for_update()
            )
        )
        for row in mail:
            row.sender = ERASED_ON_REQUEST
            row.subject = ERASED_ON_REQUEST
            row.raw = None
        await session.flush()
        if mail:
            counts["mail_cleared"] = len(mail)
        # Cleared rows no longer carry the address: the next call finds the rest, if any.
        return ErasureBatch(counts, "more" if len(mail) == ERASE_BATCH else None)


PORT = Integrations()


def register() -> None:
    """At import (the registry refuses the job while it is missing)."""
    register_person_data(PORT)
