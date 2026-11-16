"""Converting an incident to a service request and back (WP-046b S2; REQ-INC-089).

Never a type change in place: signed history is bound to the record's type (ADR-046), so the
conversion creates a new record of the other type through the ordinary create path (its own
template or catalog item, routing and SLA policy), and the old one goes to the system status
`converted` with a `converted_to` link. Its history and audit stay as they are, so they still
verify; an alias makes its old number lead to the new record (for a reader who may read it).

What carries (lane B, coordinator):
- the subject, description, requester and person it was raised for;
- custom fields the target type has with the same key and type, and only those with no
  field-access rule on the source type (a stricter reading than "the target's rule is the same
  or stricter": a ruled field never moves, so nothing a role withholds can surface);
- the conversation, by reference: the new record's timeline lists the old one's entries, each
  under its own visibility (as a merge does).
Everything else is listed in the preview and stays on the old record. Pending approvals on the
old record are withdrawn, never carried as approved. Needs edit on the old record and create on
the new type; audited with both IDs.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PermissionDenied
from app.modules import identity_access, metadata
from app.modules.identity_access import Subject
from app.modules.work_items.domain.lifecycle import (
    FINAL_CATEGORIES,
    DefaultStatus,
    StatusCategory,
    WorkItemAction,
)
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.types import (
    INCIDENT,
    SERVICE_REQUEST,
    TYPES,
    WorkItemType,
    WorkItemTypeCode,
)
from app.modules.work_items.infra.models import WorkItem, WorkItemAlias, WorkItemLink
from app.modules.work_items.service import approvals, parts
from app.modules.work_items.service import work_items as items
from app.shared.history import Change, Source

CONVERTED = DefaultStatus.CONVERTED.value
CONVERT_FIELD = "convert"  # the history change that says where it went
OTHER: dict[WorkItemTypeCode, WorkItemType] = {
    WorkItemTypeCode.INCIDENT: SERVICE_REQUEST,
    WorkItemTypeCode.SERVICE_REQUEST: INCIDENT,
}
CARRIED = ("subject", "description", "requester_id", "on_behalf_of_id")


@dataclass(frozen=True)
class ConvertPreview:
    """What a conversion would carry and leave behind (field keys only, never values)."""

    record: WorkItem
    target: WorkItemType
    carried_custom: list[str]
    not_carried: list[str]  # custom.<key>: the target lacks it, its type differs, or a rule
    pending_approvals: bool


@dataclass(frozen=True)
class Converted:
    """The old record (now `converted`) and the new one."""

    old: WorkItem
    new: items.WorkItemView
    not_carried: list[str] = field(default_factory=list)


def _open(record: WorkItem) -> bool:
    return StatusCategory(record.status_category) not in FINAL_CATEGORIES


async def _field_types(session: AsyncSession, wtype: WorkItemType) -> dict[str, Any]:
    fields = await metadata.filter_fields(session, wtype.code.value, "work_items")
    return {name.removeprefix("custom."): f.type for name, f in fields.items()}


async def preview(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> ConvertPreview:
    """What converting this record to the other type would do (nothing is changed)."""
    target = OTHER.get(wtype.code)
    if target is None:
        raise Conflict(code="not_convertible", params={"type": wtype.code.value})
    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
    if not _open(record):
        raise Conflict(code="record_closed", params={"display_id": record.display_id})
    if not subject.holds(target.permission("create")):
        raise PermissionDenied(params={"permission": target.permission("create")})
    mine = await _field_types(session, wtype)
    theirs = await _field_types(session, target)
    ruled = await identity_access.restricted_fields(session, wtype.code.value)
    carried: list[str] = []
    left: list[str] = []
    for key, value in sorted((record.custom or {}).items()):
        if value is None:
            continue
        if key in theirs and theirs[key] == mine.get(key) and f"custom.{key}" not in ruled:
            carried.append(key)
        else:
            left.append(f"custom.{key}")
    pending = bool(record.approval_status == "pending")
    return ConvertPreview(record, target, carried, left, pending)


async def convert(  # noqa: PLR0913 - the record, the target's own inputs and the context
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    target_values: dict[str, Any],
    expected_version: int,
    holders: items.PermissionHolders,
    source: Source,
) -> Converted:
    """Create the other type's record from this one and mark this one `converted`.

    `target_values` are the new type's own inputs: a service request's `catalog_item_id` and
    `answers`, an incident's `template_id` (the create path checks them).
    """
    shown = await preview(session, subject, wtype, record_id)
    record = shown.record
    if record.version != expected_version:
        raise await items.stale_record(session, record, expected_version)
    values: dict[str, Any] = {
        name: getattr(record, name) for name in CARRIED if getattr(record, name) is not None
    }
    values = {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in values.items()}
    values["custom"] = {key: record.custom[key] for key in shown.carried_custom}
    values.update(target_values)
    made = await items.create(
        session, subject, shown.target, values, source=source, holders=holders
    )
    new = made.record
    # Its old number (and any number that already led to it) now leads to the new record.
    await session.execute(
        update(WorkItemAlias)
        .where(WorkItemAlias.work_item_id == record.id, WorkItemAlias.deleted_at.is_(None))
        .values(work_item_id=new.id, version=WorkItemAlias.version + 1)
    )
    session.add(
        WorkItemAlias(tenant_id=record.tenant_id, display_id=record.display_id, work_item_id=new.id)
    )
    link = await parts.LinkRepository(session).add(
        WorkItemLink(source_id=record.id, target_id=new.id, kind=LinkKind.CONVERTED_TO.value)
    )
    await parts.link_recorded(session, record, new, link, "child_added", source)
    if shown.pending_approvals:
        await approvals.withdraw_pending(session, record)
    fresh = await session.get(WorkItem, record.id, populate_existing=True)
    assert fresh is not None  # noqa: S101 - just read above
    what = {
        "to": str(new.id),
        "to_display_id": new.display_id,
        "to_type": shown.target.code.value,
        "not_carried": shown.not_carried,
    }
    old = await items.set_status(
        session,
        wtype,
        fresh,
        WorkItemAction.CONVERT,
        target=CONVERTED,
        expected_version=fresh.version,
        source=source,
        extra=[Change(CONVERT_FIELD, None, what)],
    )
    return Converted(old, made, shown.not_carried)


@dataclass(frozen=True)
class AliasTarget:
    """Where an old number leads now."""

    record_type: WorkItemTypeCode
    record_id: uuid.UUID
    display_id: str


async def follow_alias(session: AsyncSession, subject: Subject, value: str) -> AliasTarget:
    """The record an old (converted) number leads to, for a reader who may read it; else 404.

    Never a hint that the record exists when they may not (lane B, coordinator).
    """
    wanted = value.strip().upper()[:40]
    row = await session.scalar(
        select(WorkItem)
        .join(WorkItemAlias, WorkItemAlias.work_item_id == WorkItem.id)
        .where(WorkItemAlias.display_id == wanted, WorkItemAlias.deleted_at.is_(None))
    )
    if row is None:
        raise NotFound(code="alias_not_found")
    wtype = TYPES[WorkItemTypeCode(row.type)]
    if not await items.may(session, subject, wtype, "view", row.id):
        raise NotFound(code="alias_not_found")
    return AliasTarget(wtype.code, row.id, row.display_id)
