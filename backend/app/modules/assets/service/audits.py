"""Asset audits: plan, run, settle discrepancies (WP-049b s3; REQ-AST-042, 043).

- **Who:** planning, starting, closing and applying fixes need `assets.manage`. Marking needs
  `assets.view` and to be a named auditor of that audit, and only while it runs (403
  `asset_audit_not_auditor` otherwise). Others with `assets.view` see the audits they audit;
  anyone else gets 404 (never a hint), as does another tenant (RLS).
- **Scope:** sites, product types (with the types below them) and asset groups; each left
  empty means "any". Starting freezes the expected items: the live assets in scope that the
  person starting it may see, each with its site then (042 AC1).
- **Marking:** found, missing, wrong place or damaged, by scanning (a tag, serial, barcode or
  the asset's link) or by hand. Found at another site than expected is the wrong place (043 AC1).
  An asset scanned that is not expected is added as unexpected (the auditor must see it).
- **Self-audit (042 AC2):** starting asks each holder of an asset in scope to confirm it,
  through the acknowledgement they already answer in the portal ("My assets"), asked again at
  every audit. Accepting marks the item found, disputing marks it missing and keeps the
  person's comment on the item (the discrepancy list shows it). A holder sees only their own assets.
- **Fixes (043 AC2):** move site, change state or assign, for many items at once. Each goes
  through the normal asset service (permissions, life cycle, history, events), in its own
  savepoint, and its history names the audit (`automation_ref` kind `asset_audit`).
- **Live (043 AC3):** every change goes to the audit's channel; screens refetch the progress.
- A closed audit is read-only (409 `asset_audit_closed`), on the server.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import ColumnElement, delete, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, Conflict, NotFound, PermissionDenied
from app.modules.assets.domain.audits import (
    FIX_MAX,
    NOTE_MAX,
    AuditFix,
    AuditItemKind,
    AuditItemResult,
    AuditKind,
    AuditMarkMethod,
    AuditState,
    Progress,
    is_discrepancy,
    plan_problems,
    result_of,
)
from app.modules.assets.domain.catalogue import Problem
from app.modules.assets.events import AuditAction, AuditChanged, AuditItemAction, AuditItemChanged
from app.modules.assets.infra.models import (
    Asset,
    AssetAcknowledgement,
    AssetAssignment,
    AssetAudit,
    AssetAuditAuditor,
    AssetAuditItem,
    AssetGroup,
    AssetProductType,
)
from app.modules.assets.service.acknowledgements import _changed as acknowledgement_changed
from app.modules.assets.service.assets import (
    MANAGE,
    VIEW,
    _refuse,
    _require,
    _tenant,
    _visible,
    staff_rows,
    update_asset,
)
from app.modules.assets.service.groups import _members
from app.modules.assets.service.moves import REASON_MAX, move_asset
from app.modules.assets.service.ownership import Holder, set_holder
from app.modules.identity_access import Subject, active_user_ids
from app.modules.organization import existing_unit_ids
from app.shared.clock import system_clock
from app.shared.db.display_ids import next_display_id
from app.shared.events import record_event
from app.shared.history import Change, Source, automated, record_changes
from app.shared.history.conflicts import stale_version
from app.shared.ids import new_id

RECORD_TYPE = "asset_audit"
ITEM_RECORD_TYPE = "asset_audit_item"
PREFIX = "AUD"
AUDITORS_MAX = 50
SCOPE_MAX = 100  # sites, product types or groups in one scope
ITEMS_MAX = 20_000  # expected items one audit freezes
ITEMS_LISTED = 1000
NOT_FOUND = "asset_audit_not_found"
# What may change in which state: a running audit keeps its scope (its items are frozen).
_DRAFT_FIELDS = (
    "name",
    "description",
    "site_ids",
    "product_type_ids",
    "group_ids",
    "planned_start",
    "planned_end",
)
_RUNNING_FIELDS = ("name", "description", "planned_end")


@dataclass(frozen=True, slots=True)
class AuditView:
    """An audit with its auditors and progress."""

    audit: AssetAudit
    auditors: list[uuid.UUID]
    progress: Progress
    may_manage: bool
    may_mark: bool


@dataclass(frozen=True, slots=True)
class ItemView:
    """One item with the asset's tag, name and current site (for the list and the fixes)."""

    item: AssetAuditItem
    tag: str | None
    name: str
    site_id: uuid.UUID | None
    state_id: uuid.UUID
    discrepancy: bool


@dataclass(frozen=True, slots=True)
class FixOutcome:
    """One item's fix: applied, or why not (a labelled problem code)."""

    item_id: uuid.UUID
    applied: bool
    code: str | None = None


# --- reading ----------------------------------------------------------------------------------


async def _auditors(session: AsyncSession, audit_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        await session.scalars(
            select(AssetAuditAuditor.user_id)
            .where(AssetAuditAuditor.audit_id == audit_id)
            .order_by(AssetAuditAuditor.created_at, AssetAuditAuditor.user_id)
        )
    )


async def is_auditor(session: AsyncSession, audit_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Whether the person is a named auditor of the audit."""
    found = await session.scalar(
        select(AssetAuditAuditor.user_id).where(
            AssetAuditAuditor.audit_id == audit_id, AssetAuditAuditor.user_id == user_id
        )
    )
    return found is not None


def _readable(subject: Subject) -> ColumnElement[bool]:
    """Audits the subject may open: all with assets.manage, else those they audit."""
    if subject.holds(MANAGE):
        return true()
    return AssetAudit.id.in_(
        select(AssetAuditAuditor.audit_id).where(AssetAuditAuditor.user_id == subject.user_id)
    )


async def progress(session: AsyncSession, audit: AssetAudit) -> Progress:
    """Found, marked and discrepancies out of expected (043 AC3)."""
    rows = (
        await session.execute(
            select(AssetAuditItem.kind, AssetAuditItem.result, func.count())
            .where(AssetAuditItem.audit_id == audit.id)
            .group_by(AssetAuditItem.kind, AssetAuditItem.result)
        )
    ).all()
    closed = audit.state == AuditState.CLOSED
    expected = marked = found = unexpected = gaps = 0
    for kind, result, count in rows:
        item_kind = AuditItemKind(kind)
        item_result = None if result is None else AuditItemResult(result)
        if item_kind is AuditItemKind.EXPECTED:
            expected += count
            marked += count if item_result is not None else 0
            found += count if item_result is AuditItemResult.FOUND else 0
        else:
            unexpected += count
        gaps += count if is_discrepancy(item_kind, item_result, closed=closed) else 0
    return Progress(expected, marked, found, unexpected, gaps)


async def _view(session: AsyncSession, subject: Subject, audit: AssetAudit) -> AuditView:
    auditors = await _auditors(session, audit.id)
    return AuditView(
        audit=audit,
        auditors=auditors,
        progress=await progress(session, audit),
        may_manage=subject.holds(MANAGE),
        may_mark=subject.holds(VIEW)
        and subject.user_id in auditors
        and audit.state == AuditState.RUNNING,
    )


async def list_audits(session: AsyncSession, subject: Subject) -> list[AuditView]:
    """The audits the subject may open, newest change first."""
    _require(subject, VIEW)
    rows = await session.scalars(
        select(AssetAudit)
        .where(AssetAudit.deleted_at.is_(None), _readable(subject))
        .order_by(AssetAudit.updated_at.desc(), AssetAudit.id.desc())
        .limit(500)
    )
    return [await _view(session, subject, row) for row in rows]


async def _audit(
    session: AsyncSession, subject: Subject, audit_id: uuid.UUID, *, lock: bool = False
) -> AssetAudit:
    statement = select(AssetAudit).where(
        AssetAudit.id == audit_id, AssetAudit.deleted_at.is_(None), _readable(subject)
    )
    row = await session.scalar(statement.with_for_update(of=AssetAudit) if lock else statement)
    if row is None:
        raise NotFound(code=NOT_FOUND)
    return row


async def get_audit(session: AsyncSession, subject: Subject, audit_id: uuid.UUID) -> AuditView:
    """One audit (404 when the subject may not open it)."""
    _require(subject, VIEW)
    return await _view(session, subject, await _audit(session, subject, audit_id))


async def list_items(
    session: AsyncSession,
    subject: Subject,
    audit_id: uuid.UUID,
    *,
    discrepancies_only: bool = False,
) -> list[ItemView]:
    """The audit's items: expected first, then unexpected, by tag."""
    _require(subject, VIEW)
    audit = await _audit(session, subject, audit_id)
    closed = audit.state == AuditState.CLOSED
    rows = (
        await session.execute(
            select(AssetAuditItem, Asset.tag, Asset.name, Asset.site_id, Asset.state_id)
            .join(Asset, Asset.id == AssetAuditItem.asset_id)
            .where(AssetAuditItem.audit_id == audit.id)
            .order_by(AssetAuditItem.kind, Asset.tag, AssetAuditItem.id)
            .limit(ITEMS_LISTED)
        )
    ).all()
    views = [
        ItemView(
            item=item,
            tag=tag,
            name=name,
            site_id=site,
            state_id=state,
            discrepancy=is_discrepancy(
                AuditItemKind(item.kind),
                None if item.result is None else AuditItemResult(item.result),
                closed=closed,
            ),
        )
        for item, tag, name, site, state in rows
    ]
    return [v for v in views if v.discrepancy] if discrepancies_only else views


# --- planning ---------------------------------------------------------------------------------


def _json(value: object) -> Any:  # noqa: ANN401 - history stores JSON values
    if isinstance(value, uuid.UUID | date):
        return str(value)
    if isinstance(value, list):
        return [_json(v) for v in value]
    return value


def _ids(values: Mapping[str, Any], name: str, problems: list[Problem]) -> list[uuid.UUID]:
    raw = list(dict.fromkeys(values.get(name) or []))
    if len(raw) > SCOPE_MAX:
        problems.append(Problem(name, "too_many", (("max", SCOPE_MAX),)))
    return [uuid.UUID(str(v)) for v in raw]


async def _known(
    session: AsyncSession, model: type[AssetProductType] | type[AssetGroup], ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Which of `ids` are live product types or groups."""
    if not ids:
        return set()
    return set(
        await session.scalars(select(model.id).where(model.id.in_(ids), model.deleted_at.is_(None)))
    )


async def _clean(
    session: AsyncSession, values: Mapping[str, Any], current: AssetAudit | None
) -> tuple[dict[str, Any], list[Problem]]:
    """The plan's fields sent, trimmed and checked (sites, types and groups must exist)."""
    problems: list[Problem] = []
    cleaned: dict[str, Any] = {}
    if "name" in values:
        cleaned["name"] = " ".join(str(values["name"] or "").split())
    if "description" in values:
        cleaned["description"] = (str(values["description"] or "")).strip() or None
    for name in ("planned_start", "planned_end"):
        if name in values:
            cleaned[name] = values[name]
    if "site_ids" in values:
        sites = _ids(values, "site_ids", problems)
        if set(sites) - await existing_unit_ids(session, "site", sites):
            problems.append(Problem("site_ids", "site_not_found"))
        cleaned["site_ids"] = sites
    for name, model, code in (
        ("product_type_ids", AssetProductType, "asset_product_type_not_found"),
        ("group_ids", AssetGroup, "group_not_found"),
    ):
        if name in values:
            ids = _ids(values, name, problems)
            if set(ids) - await _known(session, model, ids):
                problems.append(Problem(name, code))
            cleaned[name] = ids
    start = cleaned.get("planned_start", None if current is None else current.planned_start)
    end = cleaned.get("planned_end", None if current is None else current.planned_end)
    problems += [Problem(f, c) for f, c in plan_problems(cleaned.get("name"), start, end)]
    return cleaned, problems


async def _auditor_problems(session: AsyncSession, people: Sequence[uuid.UUID]) -> list[Problem]:
    if len(people) > AUDITORS_MAX:
        return [Problem("auditor_ids", "too_many", (("max", AUDITORS_MAX),))]
    if set(people) - set(await active_user_ids(session, list(people))):
        return [Problem("auditor_ids", "user_not_found")]
    return []


async def _set_auditors(
    session: AsyncSession, audit: AssetAudit, people: Sequence[uuid.UUID], by: uuid.UUID
) -> Change | None:
    before = await _auditors(session, audit.id)
    wanted = list(dict.fromkeys(people))
    if set(before) == set(wanted):
        return None
    await session.execute(
        delete(AssetAuditAuditor).where(
            AssetAuditAuditor.audit_id == audit.id, AssetAuditAuditor.user_id.not_in(wanted)
        )
    )
    for person in wanted:
        if person not in before:
            session.add(
                AssetAuditAuditor(
                    tenant_id=audit.tenant_id, audit_id=audit.id, user_id=person, created_by=by
                )
            )
    await session.flush()
    return Change("auditor_ids", [str(p) for p in before], [str(p) for p in wanted])


async def _saved(  # noqa: PLR0913 - one save: what, who, the changes, how, which event
    session: AsyncSession,
    subject: Subject,
    audit: AssetAudit,
    changes: list[Change],
    *,
    action: AuditAction,
    source: Source,
) -> None:
    if action != "created":
        audit.version += 1
    audit.updated_by = subject.user_id
    await session.flush()
    await session.refresh(audit)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=audit.id,
        version=audit.version,
        kind="created"
        if action == "created"
        else ("status" if action in {"started", "closed"} else "updated"),
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        AuditChanged(
            audit_id=audit.id,
            action=action,
            changed_fields=sorted({c.field for c in changes}),
            auditors=await _auditors(session, audit.id),
        ),
        aggregate_id=audit.id,
        aggregate_version=audit.version,
    )


async def create_audit(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], *, source: Source
) -> AuditView:
    """A new draft audit with its scope, dates and auditors (assets.manage)."""
    _require(subject, MANAGE)
    cleaned, problems = await _clean(session, values, None)
    if not cleaned.get("name"):
        problems = [p for p in problems if p.field != "name"] + [Problem("name", "required")]
    kind = values.get("kind")
    if kind not in set(AuditKind):
        problems.append(Problem("kind", "invalid_choice"))
    people = [uuid.UUID(str(p)) for p in dict.fromkeys(values.get("auditor_ids") or [])]
    problems += await _auditor_problems(session, people)
    _refuse(problems)
    audit = AssetAudit(
        id=new_id(),
        tenant_id=_tenant(session),
        created_by=subject.user_id,
        display_id=await next_display_id(session, PREFIX),
        kind=str(kind),
        **cleaned,
    )
    session.add(audit)
    await session.flush()
    await _set_auditors(session, audit, people, subject.user_id)
    changes = [Change(k, None, _json(v)) for k, v in cleaned.items() if v not in (None, [])]
    changes += [Change("kind", None, audit.kind)]
    if people:
        changes.append(Change("auditor_ids", None, [str(p) for p in people]))
    await _saved(session, subject, audit, changes, action="created", source=source)
    return await _view(session, subject, audit)


async def _to_change(
    session: AsyncSession, subject: Subject, audit_id: uuid.UUID, expected_version: int
) -> AssetAudit:
    _require(subject, MANAGE)
    audit = await _audit(session, subject, audit_id, lock=True)
    if audit.state == AuditState.CLOSED:
        raise Conflict(code="asset_audit_closed")
    if audit.version != expected_version:
        raise await stale_version(
            session, audit, expected_version=expected_version, record_type=RECORD_TYPE,
            record_id=audit.id,
        )  # fmt: skip
    return audit


async def update_audit(  # noqa: PLR0913 - the audit, its version, the fields and the source
    session: AsyncSession,
    subject: Subject,
    audit_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> AuditView:
    """Change the plan (If-Match): all of it as a draft; name, text, end and auditors running."""
    audit = await _to_change(session, subject, audit_id, expected_version)
    allowed = _DRAFT_FIELDS if audit.state == AuditState.DRAFT else _RUNNING_FIELDS
    frozen = [k for k in values if k not in allowed and k != "auditor_ids"]
    if frozen:
        raise Conflict(code="asset_audit_scope_frozen", params={"fields": len(frozen)})
    cleaned, problems = await _clean(session, values, audit)
    if "name" in values and not cleaned.get("name"):
        problems.append(Problem("name", "required"))
    people: list[uuid.UUID] | None = None
    if "auditor_ids" in values:
        people = [uuid.UUID(str(p)) for p in dict.fromkeys(values.get("auditor_ids") or [])]
        problems += await _auditor_problems(session, people)
    _refuse(problems)
    changes: list[Change] = []
    for field, value in cleaned.items():
        if getattr(audit, field) != value:
            changes.append(Change(field, _json(getattr(audit, field)), _json(value)))
            setattr(audit, field, value)
    if people is not None and (
        change := await _set_auditors(session, audit, people, subject.user_id)
    ):
        changes.append(change)
    if changes:
        await _saved(session, subject, audit, changes, action="updated", source=source)
    return await _view(session, subject, audit)


async def _type_tree(session: AsyncSession, roots: Sequence[uuid.UUID]) -> set[uuid.UUID]:
    """The types named and every type below them."""
    if not roots:
        return set()
    parents = dict(
        (await session.execute(select(AssetProductType.id, AssetProductType.parent_id)))
        .tuples()
        .all()
    )
    found = set(roots)
    grew = True
    while grew:
        grew = False
        for child, parent in parents.items():
            if parent in found and child not in found:
                found.add(child)
                grew = True
    return found


async def _in_scope(session: AsyncSession, subject: Subject, audit: AssetAudit) -> list[Asset]:
    """The live assets in the audit's scope that the person starting it may see (042 AC1)."""
    statement = staff_rows(subject)
    if audit.site_ids:
        statement = statement.where(Asset.site_id.in_(audit.site_ids))
    if audit.product_type_ids:
        types = await _type_tree(session, audit.product_type_ids)
        statement = statement.where(Asset.product_type_id.in_(types))
    if audit.group_ids:
        groups = list(
            await session.scalars(select(AssetGroup).where(AssetGroup.id.in_(audit.group_ids)))
        )
        members = [_members(subject, g).with_only_columns(Asset.id) for g in groups]
        statement = statement.where(or_(*(Asset.id.in_(m) for m in members)))
    rows = list(await session.scalars(statement.order_by(Asset.id).limit(ITEMS_MAX + 1)))
    if len(rows) > ITEMS_MAX:
        raise Conflict(code="asset_audit_too_large", params={"max": ITEMS_MAX})
    return rows


async def _ask_holders(session: AsyncSession, audit: AssetAudit, assets: Sequence[Asset]) -> int:
    """Self-audit: each person holding an asset in scope is asked to confirm it (042 AC2)."""
    held = {a.id: a for a in assets if a.owner_user_id is not None}
    if not held:
        return 0
    holdings = await session.scalars(
        select(AssetAssignment).where(
            AssetAssignment.asset_id.in_(list(held)),
            AssetAssignment.ended_at.is_(None),
            AssetAssignment.deleted_at.is_(None),
            AssetAssignment.holder_kind == "user",
        )
    )
    asked = 0
    for holding in holdings:
        ack = AssetAcknowledgement(
            id=new_id(),
            tenant_id=audit.tenant_id,
            created_by=audit.started_by,
            asset_id=holding.asset_id,
            assignment_id=holding.id,
            user_id=holding.holder_id,
            audit_id=audit.id,
        )
        session.add(ack)
        await session.flush()
        await acknowledgement_changed(session, ack)
        asked += 1
    return asked


async def start_audit(
    session: AsyncSession,
    subject: Subject,
    audit_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> AuditView:
    """Draft -> running: the expected items are frozen now; a self-audit asks the holders."""
    audit = await _to_change(session, subject, audit_id, expected_version)
    if audit.state != AuditState.DRAFT:
        raise Conflict(code="asset_audit_not_draft")
    if not await _auditors(session, audit.id) and audit.kind == AuditKind.TECHNICIAN:
        _refuse([Problem("auditor_ids", "required")])
    assets = await _in_scope(session, subject, audit)
    for asset in assets:
        session.add(
            AssetAuditItem(
                id=new_id(),
                tenant_id=audit.tenant_id,
                created_by=subject.user_id,
                audit_id=audit.id,
                asset_id=asset.id,
                kind=AuditItemKind.EXPECTED,
                expected_site_id=asset.site_id,
            )
        )
    audit.state = AuditState.RUNNING
    audit.started_at = system_clock.now()
    audit.started_by = subject.user_id
    await session.flush()
    if audit.kind == AuditKind.SELF:
        await _ask_holders(session, audit, assets)
    changes = [Change("state", AuditState.DRAFT.value, AuditState.RUNNING.value)]
    await _saved(session, subject, audit, changes, action="started", source=source)
    return await _view(session, subject, audit)


async def close_audit(
    session: AsyncSession,
    subject: Subject,
    audit_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> AuditView:
    """Running -> closed: read-only from now on. Pending self-audit questions are withdrawn."""
    audit = await _to_change(session, subject, audit_id, expected_version)
    if audit.state != AuditState.RUNNING:
        raise Conflict(code="asset_audit_not_running")
    audit.state = AuditState.CLOSED
    audit.closed_at = system_clock.now()
    audit.closed_by = subject.user_id
    pending = list(
        await session.scalars(
            select(AssetAcknowledgement).where(
                AssetAcknowledgement.audit_id == audit.id,
                AssetAcknowledgement.status == "pending",
                AssetAcknowledgement.deleted_at.is_(None),
            )
        )
    )
    for ack in pending:  # no longer asked: it leaves "My assets" (soft delete, kept)
        ack.deleted_at = system_clock.now()
        ack.updated_by = subject.user_id
        ack.version += 1
        await session.flush()
        await acknowledgement_changed(session, ack)
    changes = [Change("state", AuditState.RUNNING.value, AuditState.CLOSED.value)]
    await _saved(session, subject, audit, changes, action="closed", source=source)
    return await _view(session, subject, audit)


# --- marking ----------------------------------------------------------------------------------


async def _running_for_auditor(
    session: AsyncSession, subject: Subject, audit_id: uuid.UUID
) -> AssetAudit:
    """The audit, running, with the subject one of its named auditors (and assets.view)."""
    _require(subject, VIEW)
    audit = await _audit(session, subject, audit_id, lock=True)
    if not await is_auditor(session, audit.id, subject.user_id):
        raise PermissionDenied(code="asset_audit_not_auditor")
    if audit.state == AuditState.CLOSED:
        raise Conflict(code="asset_audit_closed")
    if audit.state != AuditState.RUNNING:
        raise Conflict(code="asset_audit_not_running")
    return audit


async def _item_saved(  # noqa: PLR0913 - one save of an item: who, what, how, which event
    session: AsyncSession,
    actor: uuid.UUID | None,
    item: AssetAuditItem,
    changes: list[Change],
    *,
    action: AuditItemAction,
    source: Source,
) -> None:
    if action != "added":
        item.version += 1
    item.updated_by = actor
    await session.flush()
    await session.refresh(item)
    await record_changes(
        session,
        record_type=ITEM_RECORD_TYPE,
        record_id=item.id,
        version=item.version,
        kind="created" if action == "added" else "updated",
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        AuditItemChanged(
            audit_id=item.audit_id,
            item_id=item.id,
            asset_id=item.asset_id,
            action=action,
        ),
        aggregate_id=item.id,
        aggregate_version=item.version,
    )


def _apply_mark(  # noqa: PLR0913 - the item and everything a mark sets
    item: AssetAuditItem,
    result: AuditItemResult,
    *,
    by: uuid.UUID,
    method: AuditMarkMethod,
    seen_site: uuid.UUID | None,
    note: str | None,
) -> list[Change]:
    kept = result_of(result, expected_site=item.expected_site_id, seen_site=seen_site)
    wanted: dict[str, Any] = {
        "result": kept.value,
        "method": method.value,
        "seen_site_id": seen_site,
        "note": note,
    }
    changes = [
        Change(k, _json(getattr(item, k)), _json(v))
        for k, v in wanted.items()
        if getattr(item, k) != v
    ]
    for key, value in wanted.items():
        setattr(item, key, value)
    item.marked_by = by
    item.marked_at = system_clock.now()
    return changes


def _clean_note(note: str | None) -> str | None:
    text = (note or "").strip() or None
    if text is not None and len(text) > NOTE_MAX:
        _refuse([Problem("note", "value_too_long", (("max", NOTE_MAX),))])
    return text


async def _seen_site(session: AsyncSession, site: uuid.UUID | None) -> uuid.UUID | None:
    if site is not None and site not in await existing_unit_ids(session, "site", [site]):
        _refuse([Problem("seen_site_id", "site_not_found")])
    return site


async def mark_item(  # noqa: PLR0913 - the item, its version, what was found and how
    session: AsyncSession,
    subject: Subject,
    audit_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    result: AuditItemResult,
    seen_site_id: uuid.UUID | None,
    note: str | None,
    expected_version: int,
    source: Source,
) -> AssetAuditItem:
    """Mark one item by hand (If-Match): found somewhere else is the wrong place (043 AC1)."""
    audit = await _running_for_auditor(session, subject, audit_id)
    item = await session.scalar(
        select(AssetAuditItem)
        .where(AssetAuditItem.id == item_id, AssetAuditItem.audit_id == audit.id)
        .with_for_update()
    )
    if item is None:
        raise NotFound(code="asset_audit_item_not_found")
    if item.version != expected_version:
        raise await stale_version(
            session, item, expected_version=expected_version, record_type=ITEM_RECORD_TYPE,
            record_id=item.id,
        )  # fmt: skip
    changes = _apply_mark(
        item,
        result,
        by=subject.user_id,
        method=AuditMarkMethod.MANUAL,
        seen_site=await _seen_site(session, seen_site_id),
        note=_clean_note(note),
    )
    if changes:
        await _item_saved(session, subject.user_id, item, changes, action="marked", source=source)
    return item


async def _asset_by_code(session: AsyncSession, subject: Subject, code: str) -> Asset:
    """The asset a scanned code names: its link, ID, tag, serial or barcode (ignoring case)."""
    text = code.strip()
    candidate = text.rstrip("/").rsplit("/", 1)[-1]
    try:
        asset_id: uuid.UUID | None = uuid.UUID(candidate)
    except ValueError:
        asset_id = None
    if asset_id is None:
        lowered = text.lower()
        asset_id = await session.scalar(
            select(Asset.id)
            .where(
                Asset.deleted_at.is_(None),
                or_(
                    func.lower(Asset.tag) == lowered,
                    func.lower(Asset.serial_number) == lowered,
                    func.lower(Asset.barcode) == lowered,
                ),
            )
            .limit(1)
        )
    if asset_id is None:
        raise NotFound(code="asset_not_found")
    return await _visible(session, subject, asset_id)


async def scan_mark(  # noqa: PLR0913 - the audit, the code and where it was seen
    session: AsyncSession,
    subject: Subject,
    audit_id: uuid.UUID,
    *,
    code: str,
    seen_site_id: uuid.UUID | None,
    result: AuditItemResult = AuditItemResult.FOUND,
    source: Source,
) -> AssetAuditItem:
    """Mark the scanned asset: its expected item, or a new unexpected one (the auditor sees it)."""
    audit = await _running_for_auditor(session, subject, audit_id)
    site = await _seen_site(session, seen_site_id)
    asset = await _asset_by_code(session, subject, code)
    item = await session.scalar(
        select(AssetAuditItem)
        .where(AssetAuditItem.audit_id == audit.id, AssetAuditItem.asset_id == asset.id)
        .with_for_update()
    )
    action: AuditItemAction = "marked"
    if item is None:
        item = AssetAuditItem(
            id=new_id(),
            tenant_id=audit.tenant_id,
            created_by=subject.user_id,
            audit_id=audit.id,
            asset_id=asset.id,
            kind=AuditItemKind.UNEXPECTED,
            expected_site_id=asset.site_id,
        )
        session.add(item)
        action = "added"
    changes = _apply_mark(
        item, result, by=subject.user_id, method=AuditMarkMethod.SCANNED, seen_site=site, note=None
    )
    if action == "added":
        changes = [Change("kind", None, AuditItemKind.UNEXPECTED.value), *changes]
    if changes:
        await _item_saved(session, subject.user_id, item, changes, action=action, source=source)
    return item


async def self_answered(session: AsyncSession, ack: AssetAcknowledgement) -> None:
    """A holder answered a self-audit question: accepted is found, disputed is missing."""
    audit = (
        None
        if ack.audit_id is None
        else await session.get(AssetAudit, ack.audit_id, with_for_update=True)
    )
    if audit is None or audit.state != AuditState.RUNNING:
        raise Conflict(code="asset_audit_closed")
    item = await session.scalar(
        select(AssetAuditItem)
        .where(AssetAuditItem.audit_id == audit.id, AssetAuditItem.asset_id == ack.asset_id)
        .with_for_update()
    )
    if item is None:  # a foreign key keeps the question to an expected item; never left silent
        raise NotFound(code="asset_audit_item_not_found")
    result = AuditItemResult.FOUND if ack.status == "accepted" else AuditItemResult.MISSING
    changes = _apply_mark(
        item, result, by=ack.user_id, method=AuditMarkMethod.MANUAL, seen_site=None, note=None
    )
    # Missing because the holder disputed it, with their words: told apart from "not found".
    comment = ack.comment if ack.status == "disputed" else None
    if item.dispute_comment != comment:
        changes.append(Change("dispute_comment", item.dispute_comment, comment))
        item.dispute_comment = comment
    if changes:
        await _item_saved(session, ack.user_id, item, changes, action="marked", source="portal")


# --- fixes (043 AC2) --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FixRequest:
    """One fix for many items: where to, which state, or to whom."""

    fix: AuditFix
    item_ids: Sequence[uuid.UUID]
    site_id: uuid.UUID | None = None
    state_id: uuid.UUID | None = None
    holder: Holder | None = None
    reason: str | None = None


def _fix_problems(request: FixRequest) -> list[Problem]:
    problems: list[Problem] = []
    if not request.item_ids:
        problems.append(Problem("item_ids", "required"))
    if len(request.item_ids) > FIX_MAX:
        problems.append(Problem("item_ids", "too_many", (("max", FIX_MAX),)))
    needed = {
        AuditFix.MOVE_SITE: ("site_id", request.site_id),
        AuditFix.CHANGE_STATE: ("state_id", request.state_id),
        AuditFix.ASSIGN: ("holder", request.holder),
    }[request.fix]
    if needed[1] is None:
        problems.append(Problem(needed[0], "required"))
    if request.reason is not None and len(request.reason) > REASON_MAX:
        problems.append(Problem("reason", "value_too_long", (("max", REASON_MAX),)))
    return problems


async def _fix_one(
    session: AsyncSession,
    subject: Subject,
    item: AssetAuditItem,
    request: FixRequest,
    *,
    source: Source,
) -> None:
    asset = await session.get(Asset, item.asset_id)
    if asset is None or asset.deleted_at is not None:
        raise NotFound(code="asset_not_found")
    if request.fix is AuditFix.MOVE_SITE:
        await update_asset(
            session, subject, asset.id, {"site_id": request.site_id},
            expected_version=asset.version, source=source, reason=request.reason,
        )  # fmt: skip
    elif request.fix is AuditFix.CHANGE_STATE:
        assert request.state_id is not None  # noqa: S101 - _fix_problems checked it
        await move_asset(
            session, subject, asset.id, to_state_id=request.state_id, reason=request.reason,
            expected_version=asset.version, source=source,
        )  # fmt: skip
    else:
        await set_holder(
            session, subject, asset.id, request.holder,
            expected_version=asset.version, source=source,
        )  # fmt: skip
    changes = [Change("fix", item.fix, request.fix.value)]
    item.fix = request.fix.value
    item.fixed_at = datetime.now(UTC)
    item.fixed_by = subject.user_id
    await _item_saved(session, subject.user_id, item, changes, action="fixed", source=source)


async def apply_fixes(
    session: AsyncSession,
    subject: Subject,
    audit_id: uuid.UUID,
    request: FixRequest,
    *,
    source: Source,
) -> list[FixOutcome]:
    """Apply one fix to many items, each through the asset service; per item, done or why not.

    Each asset's history names the audit (its `automation_ref`), so its record says where the
    change came from (043 AC2).
    """
    _require(subject, MANAGE)
    audit = await _audit(session, subject, audit_id, lock=True)
    if audit.state == AuditState.CLOSED:
        raise Conflict(code="asset_audit_closed")
    if audit.state != AuditState.RUNNING:
        raise Conflict(code="asset_audit_not_running")
    _refuse(_fix_problems(request))
    items = {
        i.id: i
        for i in await session.scalars(
            select(AssetAuditItem).where(
                AssetAuditItem.audit_id == audit.id,
                AssetAuditItem.id.in_(list(dict.fromkeys(request.item_ids))),
            )
        )
    }
    ref = {
        "kind": "asset_audit",
        "id": str(audit.id),
        "display_id": audit.display_id,
        "name": audit.name,
    }
    outcomes: list[FixOutcome] = []
    for item_id in dict.fromkeys(request.item_ids):
        item = items.get(item_id)
        if item is None:
            outcomes.append(FixOutcome(item_id, applied=False, code="asset_audit_item_not_found"))
            continue
        try:
            async with session.begin_nested():
                with automated(session, ref):
                    await _fix_one(session, subject, item, request, source=source)
        except AppError as error:
            await session.refresh(item)
            outcomes.append(FixOutcome(item_id, applied=False, code=error.instance_code))
        else:
            outcomes.append(FixOutcome(item_id, applied=True))
    if any(o.applied for o in outcomes):
        await _saved(
            session, subject, audit, [Change("fixes", None, sum(o.applied for o in outcomes))],
            action="fixed", source=source,
        )  # fmt: skip
    return outcomes
