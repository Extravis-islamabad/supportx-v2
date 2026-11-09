"""Who may see and attach a disposal certificate (WP-049a s3; files port, ADR-028 item 5).

The files service never reads asset tables: it asks here. Whoever may see the asset sees its
disposal certificate; attaching and removing are for those who may manage it.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
from app.modules.assets.infra.models import AssetDisposal
from app.modules.assets.service.assets import MANAGE, RECORD_TYPE, _visible
from app.modules.assets.service.realtime import RECORD_KIND
from app.modules.identity_access import Subject
from app.shared.files.ports import Action, Actor, Owner, OwnerType


def _not_found() -> NotFound:
    return NotFound(code="file_owner_not_found")


def _subject(actor: Actor) -> Subject:
    if not isinstance(actor, Subject):  # the files routes always pass the caller's Subject
        raise _not_found()
    return actor


class DisposalFileAccess:
    """`FileOwnerAccess` for disposal records."""

    owner_types = frozenset({OwnerType.ASSET_DISPOSAL})
    record_types = frozenset({RECORD_TYPE})
    channel_kind: str | None = RECORD_KIND

    async def check(
        self,
        session: AsyncSession,
        actor: Actor,
        owner_type: OwnerType,
        owner_id: uuid.UUID,
        action: Action,
    ) -> Owner:
        """The record, if `actor` may see its asset (view) or manage it (attach, remove)."""
        if owner_type != OwnerType.ASSET_DISPOSAL:
            raise _not_found()
        subject = _subject(actor)
        record = await session.get(AssetDisposal, owner_id)
        if record is None or record.deleted_at is not None:
            raise _not_found()
        try:
            await _visible(session, subject, record.asset_id)
        except (NotFound, PermissionDenied):
            raise _not_found() from None
        if action != Action.VIEW:
            await _visible(session, subject, record.asset_id, permission=MANAGE)
        return Owner(OwnerType.ASSET_DISPOSAL, record.id, RECORD_TYPE, record.asset_id)

    async def visible_owners(
        self, session: AsyncSession, actor: Actor, record_type: str, record_id: uuid.UUID
    ) -> set[tuple[OwnerType, uuid.UUID]]:
        """The asset's disposal certificate, for those who may see the asset."""
        if record_type != RECORD_TYPE:
            raise _not_found()
        try:
            await _visible(session, _subject(actor), record_id)
        except (NotFound, PermissionDenied):
            raise _not_found() from None
        found = await session.scalar(
            select(AssetDisposal.id).where(
                AssetDisposal.asset_id == record_id, AssetDisposal.deleted_at.is_(None)
            )
        )
        return set() if found is None else {(OwnerType.ASSET_DISPOSAL, found)}


FILE_ACCESS = DisposalFileAccess()
