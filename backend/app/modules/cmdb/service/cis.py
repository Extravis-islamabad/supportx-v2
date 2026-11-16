"""Configuration items (WP-053 S1; REQ-CMDB-002, 003, 005, 024 write side, 031).

Each write, in one transaction: the right and the record's scope, the domain rules, the row with
optimistic concurrency (If-Match), field history, a snapshot in `cmdb_ci_versions`, and the outbox
event. Scopes of `cmdb.view` (and the write rights): all, site (the CI's site), group (its owner
or managing group). `cmdb.manage`, reserved before S1, covers add, edit and delete.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PermissionDenied
from app.modules import assets
from app.modules.cmdb.domain import types as domain
from app.modules.cmdb.events import CiCreated, CiDeleted, CiRestored, CiUpdated
from app.modules.cmdb.infra.models import Ci, CiState, CiType, CiVersion
from app.modules.cmdb.service.catalogue import (
    ADD,
    DELETE,
    EDIT,
    MANAGE,
    VIEW,
    attributes_of,
    default_state,
    ensure_defaults,
    get_settings,
    get_state,
    get_type,
    invalid,
)
from app.modules.identity_access import (
    ResourceType,
    Subject,
    active_user_ids,
    authorize_stored,
    scope_filter,
    user_names,
)
from app.modules.organization import existing_unit_ids
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.api.listing import ListQuery, PageResult, paginate
from app.shared.db.display_ids import next_display_id
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import (
    Change,
    HistoryEntry,
    Source,
    count_saves,
    explain_conflict,
    history_page,
    record_changes,
)
from app.shared.ids import new_id

RECORD_TYPE = "ci"
DISPLAY_PREFIX = "CI"
FROM_ASSETS_MAX = 100
PICKER_MAX = 50
# Fields a person edits (the type changes through its own action, with a preview).
EDITABLE = (
    "name",
    "description",
    "state_id",
    "site_id",
    "owner_user_id",
    "owner_group_id",
    "managed_by_group_id",
    "business_impact",
    "criticality",
    "custom",
)
SNAPSHOT = ("type_id", *EDITABLE, "asset_id", "source")

CI_FIELDS = ResourceFields(
    name="cis",
    fields={
        "id": FilterField(Ci.id, FieldType.UUID),
        "display_id": FilterField(Ci.display_id, FieldType.STRING, sortable=True),
        "name": FilterField(Ci.name, FieldType.STRING, sortable=True),
        "type_id": FilterField(Ci.type_id, FieldType.UUID),
        "state_id": FilterField(Ci.state_id, FieldType.UUID),
        "site_id": FilterField(Ci.site_id, FieldType.UUID),
        "owner_user_id": FilterField(Ci.owner_user_id, FieldType.UUID),
        "owner_group_id": FilterField(Ci.owner_group_id, FieldType.UUID),
        "managed_by_group_id": FilterField(Ci.managed_by_group_id, FieldType.UUID),
        "asset_id": FilterField(Ci.asset_id, FieldType.UUID),
        "business_impact": FilterField(
            Ci.business_impact, FieldType.ENUM, values=frozenset(i.value for i in domain.CiImpact)
        ),
        "criticality": FilterField(
            Ci.criticality, FieldType.ENUM, values=frozenset(i.value for i in domain.CiImpact)
        ),
        "source": FilterField(
            Ci.source, FieldType.ENUM, values=frozenset(s.value for s in domain.CiSource)
        ),
        "created_at": FilterField(Ci.created_at, FieldType.DATETIME, sortable=True, simple=False),
        "updated_at": FilterField(Ci.updated_at, FieldType.DATETIME, sortable=True, simple=False),
    },
    id_column=Ci.id,
    default_sort=("-updated_at",),
)


def _in_sites(site_ids: frozenset[uuid.UUID]) -> ColumnElement[bool]:
    return Ci.site_id.in_(site_ids)


def _in_groups(group_ids: frozenset[uuid.UUID]) -> ColumnElement[bool]:
    return or_(Ci.owner_group_id.in_(group_ids), Ci.managed_by_group_id.in_(group_ids))


CIS = ResourceType(
    name="cis",
    fields=CI_FIELDS,
    owner_columns=(Ci.owner_user_id,),
    site_scope=_in_sites,
    group_scope=_in_groups,
)


class CiRepository(Repository[Ci]):
    """CIs of the session's tenant."""

    model = Ci


def _now() -> datetime:
    return datetime.now(UTC)


def writer(subject: Subject, permission: str) -> str | None:
    """The right this person writes with: the named one, else `cmdb.manage`, else none."""
    if subject.holds(permission):
        return permission
    return MANAGE if subject.holds(MANAGE) else None


def _denied(permission: str) -> PermissionDenied:
    return PermissionDenied(params={"permission": permission, "reason": "no_permission"})


# --- views ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CiView:
    """Everything staff see about one CI."""

    record: Ci
    attributes: list[dict[str, Any]]
    history_count: int
    can_edit: bool
    can_delete: bool


async def _may(session: AsyncSession, subject: Subject, permission: str, ci_id: uuid.UUID) -> bool:
    key = (
        writer(subject, permission)
        if permission != VIEW
        else (VIEW if subject.holds(VIEW) else None)
    )
    if key is None:
        return False
    return bool(await authorize_stored(session, subject, key, CIS, Ci.id, ci_id))


async def _view(session: AsyncSession, subject: Subject, record: Ci) -> CiView:
    return CiView(
        record=record,
        attributes=await attributes_of(session, record.type_id),
        history_count=await count_saves(session, RECORD_TYPE, record.id),
        can_edit=await _may(session, subject, EDIT, record.id),
        can_delete=await _may(session, subject, DELETE, record.id),
    )


def visible_rows(subject: Subject, *, trash: bool = False) -> Select[Any]:
    """CIs the person may see (scope-filtered)."""
    deleted = Ci.deleted_at.is_not(None) if trash else Ci.deleted_at.is_(None)
    return select(Ci).where(deleted, scope_filter(subject, VIEW, CIS))


async def list_cis(  # noqa: PLR0913 - the list query and its type filter, keyword-only
    session: AsyncSession,
    subject: Subject,
    query: ListQuery,
    *,
    type_id: uuid.UUID | None = None,
    with_subtypes: bool = True,
    trash: bool = False,
) -> PageResult[Ci]:
    """One page of CIs; `type_id` narrows to a type (and the types below it)."""
    await ensure_defaults(session)
    rows = visible_rows(subject, trash=trash)
    if type_id is not None:
        rows = rows.where(
            Ci.type_id.in_(await _subtree(session, type_id, with_subtypes=with_subtypes))
        )
    return await paginate(session, rows, query)


async def _subtree(
    session: AsyncSession, type_id: uuid.UUID, *, with_subtypes: bool
) -> list[uuid.UUID]:
    if not with_subtypes:
        return [type_id]
    rows = (
        await session.execute(
            select(CiType.id, CiType.parent_id).where(CiType.deleted_at.is_(None))
        )
    ).tuples()
    children: dict[uuid.UUID, list[uuid.UUID]] = {}
    for child, parent in rows:
        if parent is not None:
            children.setdefault(parent, []).append(child)
    found, todo = [type_id], [type_id]
    while todo:
        for child in children.get(todo.pop(), []):
            if child not in found:
                found.append(child)
                todo.append(child)
    return found


async def _visible(
    session: AsyncSession, subject: Subject, ci_id: uuid.UUID, *, trash: bool = False
) -> Ci:
    record: Ci | None = await session.scalar(
        visible_rows(subject, trash=trash).where(Ci.id == ci_id)
    )
    if record is None:
        raise NotFound(code="cmdb_ci_not_found")
    return record


async def get_ci(session: AsyncSession, subject: Subject, ci_id: uuid.UUID) -> CiView:
    """One CI the person may see (404 otherwise, never 403)."""
    return await _view(session, subject, await _visible(session, subject, ci_id))


async def history(
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    *,
    before_version: int | None,
    limit: int,
) -> tuple[list[HistoryEntry], int | None, dict[str, str]]:
    """Saves of a CI the person may see, with the actors' names."""
    await _visible(session, subject, ci_id)
    entries, cursor = await history_page(
        session, RECORD_TYPE, ci_id, before_version=before_version, limit=limit
    )
    names = await user_names(session, sorted({e.actor_id for e in entries if e.actor_id}))
    return entries, cursor, names


# --- writing --------------------------------------------------------------------------------------


def _json(value: object) -> Any:  # noqa: ANN401 - history and snapshots store JSON values
    return str(value) if isinstance(value, uuid.UUID) else value


def snapshot(record: Ci) -> dict[str, Any]:
    """The CI's saved fields as JSON (a version's snapshot; history's values)."""
    return {name: _json(getattr(record, name)) for name in SNAPSHOT}


async def _save_version(session: AsyncSession, record: Ci, subject: Subject) -> None:
    """Append the CI as it is now (REQ-CMDB-024's write side; the app may only add)."""
    await session.execute(
        insert(CiVersion).values(
            tenant_id=record.tenant_id,
            id=new_id(),
            ci_id=record.id,
            version=record.version,
            snapshot=snapshot(record),
            saved_by=subject.user_id,
        )
    )


def _check_codes(values: Mapping[str, Any]) -> list[domain.Problem]:
    problems: list[domain.Problem] = []
    if "name" in values:
        name = values["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > domain.NAME_MAX:
            problems.append(domain.Problem("name", "invalid_value"))
    description = values.get("description")
    if description is not None and (
        not isinstance(description, str) or len(description) > domain.DESCRIPTION_MAX
    ):
        problems.append(domain.Problem("description", "value_too_long"))
    impacts = {i.value for i in domain.CiImpact}
    problems += [
        domain.Problem(key, "invalid_choice")
        for key in ("business_impact", "criticality")
        if values.get(key) is not None and values[key] not in impacts
    ]
    return problems


async def _check_references(session: AsyncSession, values: Mapping[str, Any]) -> None:
    problems: list[domain.Problem] = []
    if values.get("state_id") is not None:
        state = await session.scalar(
            select(CiState.id).where(CiState.id == values["state_id"], CiState.deleted_at.is_(None))
        )
        if state is None:
            problems.append(domain.Problem("state_id", "not_found"))
    if values.get("site_id") is not None and not await existing_unit_ids(
        session, "site", [values["site_id"]]
    ):
        problems.append(domain.Problem("site_id", "not_found"))
    problems += [
        domain.Problem(key, "not_found")
        for key in ("owner_group_id", "managed_by_group_id")
        if values.get(key) is not None
        and not await existing_unit_ids(session, "group", [values[key]])
    ]
    if values.get("owner_user_id") is not None and not await active_user_ids(
        session, [values["owner_user_id"]]
    ):
        problems.append(domain.Problem("owner_user_id", "not_found"))
    if problems:
        raise invalid(problems)


async def _within_scope(
    session: AsyncSession, subject: Subject, permission: str, ci_id: uuid.UUID
) -> None:
    """The saved CI must stay where the person may write (no writing a CI out of reach)."""
    key = writer(subject, permission)
    if key is None or not await authorize_stored(session, subject, key, CIS, Ci.id, ci_id):
        raise PermissionDenied(params={"permission": permission, "reason": "out_of_scope"})


async def _names(session: AsyncSession, ids: Sequence[str]) -> list[str]:
    return list((await user_names(session, list(ids))).values())


async def _conflict(session: AsyncSession, error: Conflict, ci_id: uuid.UUID) -> Conflict:
    return await explain_conflict(
        session,
        error,
        record_type=RECORD_TYPE,
        record_id=ci_id,
        names=lambda ids: _names(session, ids),
    )


async def _add(  # noqa: PLR0913 - every part of a new CI, explicit
    session: AsyncSession,
    subject: Subject,
    values: Mapping[str, Any],
    source: Source,
    *,
    origin: domain.CiSource = domain.CiSource.MANUAL,
    asset_id: uuid.UUID | None = None,
) -> Ci:
    problems = _check_codes(values)
    if "name" not in values:
        problems.append(domain.Problem("name", "required"))
    if values.get("type_id") is None:
        problems.append(domain.Problem("type_id", "required"))
    if problems:
        raise invalid(problems)
    ci_type = await get_type(session, values["type_id"])
    custom = dict(values.get("custom") or {})
    attributes = await attributes_of(session, ci_type.id)
    if found := domain.custom_problems(custom, attributes, creating=True):
        raise invalid(found)
    await _check_references(session, values)
    state_id = values.get("state_id") or (await default_state(session)).id
    record = Ci(
        display_id=await next_display_id(session, DISPLAY_PREFIX),
        type_id=ci_type.id,
        state_id=state_id,
        name=str(values["name"]).strip(),
        description=values.get("description"),
        site_id=values.get("site_id"),
        owner_user_id=values.get("owner_user_id"),
        owner_group_id=values.get("owner_group_id"),
        managed_by_group_id=values.get("managed_by_group_id"),
        business_impact=values.get("business_impact"),
        criticality=values.get("criticality"),
        asset_id=asset_id,
        source=origin.value,
        custom=custom,
    )
    await CiRepository(session).add(record)
    await _within_scope(session, subject, ADD, record.id)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="created",
        changes=[Change(k, None, v) for k, v in snapshot(record).items() if v not in (None, {})],
        source=source,
    )
    await _save_version(session, record, subject)
    await record_event(
        session,
        CiCreated(ci_id=record.id, type_id=record.type_id, source=record.source, asset_id=asset_id),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    return record


async def create(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], source: Source
) -> CiView:
    """A new CI by hand."""
    if writer(subject, ADD) is None:
        raise _denied(ADD)
    await ensure_defaults(session)
    return await _view(session, subject, await _add(session, subject, values, source))


async def _writable(
    session: AsyncSession, subject: Subject, permission: str, ci_id: uuid.UUID
) -> Ci:
    """404 if the person cannot see it, 403 if they see it but may not write it."""
    record = await _visible(session, subject, ci_id)
    await _within_scope(session, subject, permission, ci_id)
    return record


async def _save(  # noqa: PLR0913 - the record, the version and the change, explicit
    session: AsyncSession,
    subject: Subject,
    record: Ci,
    *,
    expected_version: int,
    columns: Mapping[str, Any],
    source: Source,
) -> Ci:
    before = snapshot(record)
    if not columns:
        if record.version != expected_version:
            raise await _conflict(
                session,
                Conflict(
                    code="version_conflict",
                    params={
                        "expected_version": expected_version,
                        "current_version": record.version,
                    },
                ),
                record.id,
            )
        return record
    try:
        updated = await CiRepository(session).update(
            record.id, expected_version=expected_version, changes=columns
        )
    except Conflict as error:
        raise await _conflict(session, error, record.id) from error
    await _within_scope(session, subject, EDIT, updated.id)
    after = snapshot(updated)
    changes = [Change(k, before[k], v) for k, v in after.items() if before[k] != v]
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="updated",
        changes=changes,
        source=source,
    )
    await _save_version(session, updated, subject)
    await record_event(
        session,
        CiUpdated(
            ci_id=updated.id, type_id=updated.type_id, changed_fields=[c.field for c in changes]
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    return updated


async def update(  # noqa: PLR0913 - the record, the version and the change, explicit
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
) -> CiView:
    """Change the fields sent (If-Match). Unchanged input: no new version, no event."""
    record = await _writable(session, subject, EDIT, ci_id)
    draft = {k: v for k, v in values.items() if k in EDITABLE}
    if problems := _check_codes(draft):
        raise invalid(problems)
    if "custom" in draft:
        # Values sent merge into the CI's; a None removes one.
        merged = {**record.custom, **(draft["custom"] or {})}
        merged = {k: v for k, v in merged.items() if v is not None}
        attributes = await attributes_of(session, record.type_id)
        if found := domain.custom_problems(merged, attributes, creating=False):
            raise invalid(found)
        draft["custom"] = merged
    await _check_references(session, {k: v for k, v in draft.items() if v != getattr(record, k)})
    if "name" in draft:
        draft["name"] = str(draft["name"]).strip()
    columns = {k: v for k, v in draft.items() if getattr(record, k) != v}
    saved = await _save(
        session, subject, record, expected_version=expected_version, columns=columns, source=source
    )
    return await _view(session, subject, saved)


@dataclass(frozen=True)
class TypeChangePreview:
    """What changing a CI's type would do: the values it would lose (by key)."""

    lost: list[str]
    attributes: list[dict[str, Any]]


async def preview_type_change(
    session: AsyncSession, subject: Subject, ci_id: uuid.UUID, type_id: uuid.UUID
) -> TypeChangePreview:
    """The attribute values lost by moving the CI to another type (REQ-CMDB-003)."""
    record = await _writable(session, subject, EDIT, ci_id)
    new_type = await get_type(session, type_id)
    attributes = await attributes_of(session, new_type.id)
    return TypeChangePreview(domain.lost_on_change(record.custom, attributes), attributes)


async def change_type(  # noqa: PLR0913 - the record, the version and the change, explicit
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    *,
    type_id: uuid.UUID,
    expected_version: int,
    source: Source,
) -> CiView:
    """Move the CI to another type; values its new type does not hold are dropped."""
    preview = await preview_type_change(session, subject, ci_id, type_id)
    record = await _visible(session, subject, ci_id)
    columns: dict[str, Any] = {}
    if record.type_id != type_id:
        keep = {a["key"] for a in preview.attributes}
        columns = {
            "type_id": type_id,
            "custom": {k: v for k, v in record.custom.items() if k in keep},
        }
    saved = await _save(
        session, subject, record, expected_version=expected_version, columns=columns, source=source
    )
    return await _view(session, subject, saved)


async def copy(session: AsyncSession, subject: Subject, ci_id: uuid.UUID, source: Source) -> CiView:
    """A new CI with the same type, fields and values (never the asset link)."""
    if writer(subject, ADD) is None:
        raise _denied(ADD)
    original = await _visible(session, subject, ci_id)
    values = {k: getattr(original, k) for k in ("type_id", *EDITABLE)}
    record = await _add(session, subject, values, source)
    return await _view(session, subject, record)


async def remove(
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Move to the trash (recoverable)."""
    record = await _writable(session, subject, DELETE, ci_id)
    try:
        deleted = await CiRepository(session).soft_delete(
            record.id, expected_version=expected_version
        )
    except Conflict as error:
        raise await _conflict(session, error, record.id) from error
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=deleted.version,
        kind="deleted",
        changes=[],
        source=source,
    )
    await record_event(
        session,
        CiDeleted(ci_id=record.id, type_id=record.type_id),
        aggregate_id=record.id,
        aggregate_version=deleted.version,
    )


async def restore(
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> CiView:
    """Take out of the trash, exactly as it was (refused if its asset has a new CI since)."""
    record = await _visible(session, subject, ci_id, trash=True)
    key = writer(subject, DELETE)
    in_scope = key is not None and await session.scalar(
        select(Ci.id).where(Ci.id == ci_id, scope_filter(subject, key, CIS))
    )
    if not in_scope:
        raise NotFound(code="cmdb_ci_not_found")
    if record.version != expected_version:
        raise await _conflict(
            session,
            Conflict(
                code="version_conflict",
                params={"expected_version": expected_version, "current_version": record.version},
            ),
            record.id,
        )
    if record.asset_id is not None:
        taken = await session.scalar(
            select(Ci.id).where(Ci.asset_id == record.asset_id, Ci.deleted_at.is_(None))
        )
        if taken is not None:
            raise Conflict(code="cmdb_asset_has_ci")
    record.deleted_at = None
    record.version += 1
    record.updated_at = _now()
    record.updated_by = subject.user_id
    await session.flush()
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="restored",
        changes=[],
        source=source,
    )
    await _save_version(session, record, subject)
    await record_event(
        session,
        CiRestored(ci_id=record.id, type_id=record.type_id),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    return await _view(session, subject, record)


# --- from assets (REQ-CMDB-005) -------------------------------------------------------------------


@dataclass(frozen=True)
class FromAssetsResult:
    """CIs made, and assets skipped with why (`hidden`, `gone`, `has_ci`)."""

    created: list[Ci]
    skipped: list[tuple[uuid.UUID, str]]


async def from_assets(  # noqa: PLR0913 - the assets and the CIs' shared fields, explicit
    session: AsyncSession,
    subject: Subject,
    asset_ids: Sequence[uuid.UUID],
    *,
    type_id: uuid.UUID,
    state_id: uuid.UUID | None,
    source: Source,
) -> FromAssetsResult:
    """One CI per asset the person may see, named after it; assets with a CI are skipped.

    Through the assets module's public interface only (`asset_refs`): never its tables.
    """
    if writer(subject, ADD) is None:
        raise _denied(ADD)
    unique = list(dict.fromkeys(asset_ids))
    if not unique or len(unique) > FROM_ASSETS_MAX:
        raise invalid([domain.Problem("asset_ids", "too_many" if unique else "required")])
    await ensure_defaults(session)
    await get_type(session, type_id)
    if state_id is not None:
        await get_state(session, state_id)
    refs = await assets.asset_refs(session, subject, unique)
    taken = set(
        await session.scalars(
            select(Ci.asset_id).where(Ci.asset_id.in_(unique), Ci.deleted_at.is_(None))
        )
    )
    created: list[Ci] = []
    skipped: list[tuple[uuid.UUID, str]] = []
    for ref in refs.values():
        if ref.hidden or ref.gone or ref.name is None:
            skipped.append((ref.id, "hidden" if ref.hidden else "gone"))
            continue
        if ref.id in taken:
            skipped.append((ref.id, "has_ci"))
            continue
        values = {"type_id": type_id, "state_id": state_id, "name": ref.name}
        created.append(
            await _add(
                session,
                subject,
                values,
                source,
                origin=domain.CiSource.ASSET_SYNC,
                asset_id=ref.id,
            )
        )
    return FromAssetsResult(created, skipped)


# --- picker (REQ-CMDB-031) ------------------------------------------------------------------------


async def picker(
    session: AsyncSession,
    subject: Subject,
    *,
    search: str | None,
    type_id: uuid.UUID | None,
    limit: int = 20,
) -> list[Ci]:
    """CIs to choose from: what the person may see, end-of-life ones left out if the tenant says."""
    settings = await get_settings(session)
    rows = visible_rows(subject)
    if settings.exclude_eol_from_pickers:
        rows = rows.where(
            Ci.state_id.in_(
                select(CiState.id).where(CiState.category == domain.CiStateCategory.ACTIVE.value)
            )
        )
    if type_id is not None:
        rows = rows.where(Ci.type_id.in_(await _subtree(session, type_id, with_subtypes=True)))
    if search and search.strip():
        text = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{text}%"
        rows = rows.where(
            or_(Ci.name.ilike(term, escape="\\"), Ci.display_id.ilike(term, escape="\\"))
        )
    rows = rows.order_by(func.lower(Ci.name), Ci.id).limit(max(1, min(limit, PICKER_MAX)))
    return list(await session.scalars(rows))
