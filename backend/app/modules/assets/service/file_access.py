"""Who may see and attach an asset's files (files port, ADR-028 item 5).

The files service never reads asset tables: it asks here. Two owners: a disposal certificate
(WP-049a s3) and, since WP-049b s2 (REQ-AST-050), the asset's own attachments (invoices,
photos). Whoever may see the asset sees both; attaching and removing are for those who may
manage it. Scanning and refusing infected files is the files service's, as on incidents
(REQ-INC-079).
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
    """`FileOwnerAccess` for disposal records and assets."""

    owner_types = frozenset({OwnerType.ASSET_DISPOSAL, OwnerType.ASSET})
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
        if owner_type not in self.owner_types:
            raise _not_found()
        subject = _subject(actor)
        if owner_type == OwnerType.ASSET:
            try:
                await _visible(session, subject, owner_id)
            except (NotFound, PermissionDenied):
                raise _not_found() from None
            if action != Action.VIEW:
                await _visible(session, subject, owner_id, permission=MANAGE)
            return Owner(OwnerType.ASSET, owner_id, RECORD_TYPE, owner_id)
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
        """The asset's attachments and its disposal certificate, for those who may see it."""
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
        owners = {(OwnerType.ASSET, record_id)}
        return owners if found is None else owners | {(OwnerType.ASSET_DISPOSAL, found)}


FILE_ACCESS = DisposalFileAccess()
