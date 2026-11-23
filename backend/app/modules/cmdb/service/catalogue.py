"""CI types, CI states and the CMDB settings (WP-053 S1; REQ-CMDB-001, 004, 031).

Each tenant's built-in types and states are made the first time its CMDB is used: the settings
row is the marker, so only the transaction that inserts it seeds the rest (as assets do). Every
change raises `cmdb.config_changed` through the outbox and is audited by its route.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, func, select, true
from sqlalchemy.dialects.postgresql import array, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed
from app.modules import metadata
from app.modules.cmdb.domain import field_access as field_rules
from app.modules.cmdb.domain import types as domain
from app.modules.cmdb.events import CmdbConfigChanged
from app.modules.cmdb.infra.models import Ci, CiState, CiType, CmdbSettings
from app.modules.identity_access import Subject
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import stale_version
from app.shared.ids import new_id

VIEW = "cmdb.view"
ADD = "cmdb.add"
EDIT = "cmdb.edit"
DELETE = "cmdb.delete"
CONFIGURE = "cmdb.configure"
# Reserved before S1 (identity_access) and still granted to the asset manager: it covers every
# CI write (add, edit, delete), so a role that holds it keeps working with no data step.
MANAGE = "cmdb.manage"

TYPE_RECORD = "cmdb_ci_type"
STATE_RECORD = "cmdb_ci_state"
SETTINGS_RECORD = uuid.UUID(int=0)


def tenant_of(session: AsyncSession) -> uuid.UUID:
    """The session's tenant."""
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant


def require_configure(subject: Subject) -> None:
    """403 unless the person may change the CMDB's types, states and settings."""
    if not subject.holds(CONFIGURE):
        raise PermissionDenied(params={"permission": CONFIGURE, "reason": "no_permission"})


def invalid(problems: Sequence[domain.Problem]) -> ValidationFailed:
    """422 listing every problem (`errors.field.<code>`)."""
    return ValidationFailed(
        errors=[
            FieldError(field=f"body.{p.field}", code=p.code, message_key=f"errors.field.{p.code}")
            for p in problems
        ]
    )


async def ensure_defaults(session: AsyncSession) -> None:
    """The settings row and, the first time, the built-in types and states (idempotent)."""
    if session.info.get("cmdb.defaults"):
        return
    tenant = tenant_of(session)
    inserted = await session.execute(
        insert(CmdbSettings)
        .values(tenant_id=tenant)
        .on_conflict_do_nothing()
        .returning(CmdbSettings.tenant_id)
    )
    if inserted.scalar() is None:
        session.info["cmdb.defaults"] = True
        return
    ids: dict[str, uuid.UUID] = {}
    for code, parent, icon in domain.BUILT_IN_TYPES:
        ids[code] = new_id()
        session.add(
            CiType(
                id=ids[code],
                tenant_id=tenant,
                parent_id=ids[parent] if parent else None,
                api_name=code,
                built_in=True,
                names={},
                icon=icon,
                relationship_types=[],
            )
        )
        await session.flush()  # a parent before its children (composite foreign key)
    for position, (code, category) in enumerate(domain.BUILT_IN_STATES):
        session.add(
            CiState(
                id=new_id(),
                tenant_id=tenant,
                api_name=code,
                built_in=True,
                names={},
                category=category.value,
                position=position,
            )
        )
    await session.flush()


async def _config_event(
    session: AsyncSession, what: str, action: str, item_id: uuid.UUID | None, version: int
) -> None:
    await record_event(
        session,
        CmdbConfigChanged(what=what, action=action, item_id=item_id),
        aggregate_id=item_id or SETTINGS_RECORD,
        aggregate_version=version,
    )


# Other parts of the module (relationship types, S2) raise the same event.
config_event = _config_event


# --- types ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TypeView:
    """One CI type and how many CIs and child types it has."""

    record: CiType
    ci_count: int
    child_count: int


async def _parents(session: AsyncSession) -> dict[str, str | None]:
    rows = await session.execute(
        select(CiType.id, CiType.parent_id).where(CiType.deleted_at.is_(None))
    )
    return {str(i): (str(p) if p else None) for i, p in rows}


async def list_types(
    session: AsyncSession, *, visible: ColumnElement[bool] | None = None
) -> list[TypeView]:
    """Every live type, with counts (the type tree of the CMDB home).

    `visible`: the reader's CI scope (lane C 2, ADR-053): counted only within it, so a count
    never tells anyone about CIs they may not see. Without it (configuration paths), all CIs.
    """
    await ensure_defaults(session)
    rows = list(
        await session.scalars(
            select(CiType).where(CiType.deleted_at.is_(None)).order_by(CiType.api_name)
        )
    )
    counts = dict(
        (
            await session.execute(
                select(Ci.type_id, func.count())
                .where(Ci.deleted_at.is_(None), true() if visible is None else visible)
                .group_by(Ci.type_id)
            )
        ).all()  # a Result has keys(): dict() would read it as a mapping
    )
    children: dict[uuid.UUID, int] = {}
    for r in rows:
        if r.parent_id:
            children[r.parent_id] = children.get(r.parent_id, 0) + 1
    return [
        TypeView(
            record=r,
            ci_count=int(counts.get(r.id, 0)),
            child_count=children.get(r.id, 0),
        )
        for r in rows
    ]


async def get_type(session: AsyncSession, type_id: uuid.UUID) -> CiType:
    """A live type (404 `cmdb_ci_type_not_found`)."""
    await ensure_defaults(session)
    row = await session.scalar(
        select(CiType).where(CiType.id == type_id, CiType.deleted_at.is_(None))
    )
    if row is None:
        raise NotFound(code="cmdb_ci_type_not_found")
    return row


async def _type_view(session: AsyncSession, row: CiType) -> TypeView:
    return next(v for v in await list_types(session) if v.record.id == row.id)


def _check_type(values: Mapping[str, Any], *, built_in: bool, creating: bool) -> None:
    problems: list[domain.Problem] = []
    if creating:
        api_name = values.get("api_name")
        if not isinstance(api_name, str) or not domain.API_NAME.fullmatch(api_name):
            problems.append(domain.Problem("api_name", "invalid_key"))
    if "names" in values or creating:
        problems += domain.names_problems(values.get("names"), required=not built_in)
    if problems:
        raise invalid(problems)


async def _check_parent(
    session: AsyncSession, type_id: uuid.UUID, parent_id: uuid.UUID | None
) -> None:
    if parent_id is None:
        return
    await get_type(session, parent_id)
    parents = await _parents(session)
    if domain.would_loop(str(type_id), str(parent_id), parents):
        raise invalid([domain.Problem("parent_id", "cmdb_ci_type_loop")])
    if domain.depth(str(parent_id), parents) + 1 > domain.TYPE_DEPTH_MAX:
        raise invalid([domain.Problem("parent_id", "cmdb_ci_type_too_deep")])


async def _api_name_free(session: AsyncSession, model: type[Any], api_name: str) -> None:
    taken = await session.scalar(
        select(model.id).where(model.api_name == api_name, model.deleted_at.is_(None))
    )
    if taken is not None:
        raise invalid([domain.Problem("api_name", "duplicate")])


async def create_type(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any]
) -> TypeView:
    """A tenant's own type below a parent (or at the top)."""
    require_configure(subject)
    await ensure_defaults(session)
    _check_type(values, built_in=False, creating=True)
    await _api_name_free(session, CiType, values["api_name"])
    row = CiType(
        id=new_id(),
        parent_id=values.get("parent_id"),
        api_name=values["api_name"],
        built_in=False,
        names=dict(values["names"]),
        icon=values.get("icon"),
        relationship_types=[],
    )
    await _check_parent(session, row.id, row.parent_id)
    await TypeRepository(session).add(row)
    await _config_event(session, "type", "created", row.id, row.version)
    return await _type_view(session, row)


class TypeRepository(Repository[CiType]):
    """CI types of the session's tenant."""

    model = CiType


class StateRepository(Repository[CiState]):
    """CI states of the session's tenant."""

    model = CiState


async def update_type(
    session: AsyncSession,
    subject: Subject,
    type_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
) -> TypeView:
    """Rename, move or re-icon a type (If-Match).

    A built-in type keeps its code and place; its names may be overridden.
    """
    require_configure(subject)
    row = await get_type(session, type_id)
    if row.built_in and "parent_id" in values and values["parent_id"] != row.parent_id:
        raise Conflict(code="cmdb_built_in_locked")
    _check_type(values, built_in=row.built_in, creating=False)
    if "parent_id" in values:
        await _check_parent(session, row.id, values["parent_id"])
    changes = {
        k: v
        for k, v in values.items()
        if k in {"parent_id", "names", "icon"} and getattr(row, k) != v
    }
    if not changes:
        if row.version != expected_version:
            raise await stale_version(session, row, expected_version=expected_version)
        return await _type_view(session, row)
    updated = await TypeRepository(session).update(
        row.id, expected_version=expected_version, changes=changes
    )
    if "parent_id" in changes:
        await _check_move(session, updated.id)
    await _config_event(session, "type", "updated", updated.id, updated.version)
    return await _type_view(session, updated)


async def _subtree(session: AsyncSession, type_id: uuid.UUID) -> list[uuid.UUID]:
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


async def _check_move(session: AsyncSession, type_id: uuid.UUID) -> None:
    """After a type moved under a new parent: no CI below it may hold a value it would lose.

    Runs on the moved tree inside the same transaction (metadata's lineages forgotten first), so
    the check sees exactly what CIs would see from now on; a refusal (409
    `cmdb_ci_type_move_drops_fields`, with the count) rolls the move back with it (0175 §4).
    """
    entity = metadata.CustomFieldEntity.CI
    metadata.forget_lineage(session, entity)
    known = [f.key for f in await metadata.field_marks(session, entity, retired=True)]
    if not known:
        return
    affected = 0
    for each in await _subtree(session, type_id):
        kept = {
            f.key for f in await metadata.field_marks(session, entity, retired=True, type_id=each)
        }
        lost = [k for k in known if k not in kept]
        if not lost:
            continue
        holders = await session.scalars(
            select(Ci.custom).where(Ci.type_id == each, Ci.custom.has_any(array(lost)))
        )
        affected += sum(1 for custom in holders if field_rules.dropped(custom or {}, kept, known))
    if affected:
        raise Conflict(code="cmdb_ci_type_move_drops_fields", params={"ci_count": affected})


async def delete_type(
    session: AsyncSession, subject: Subject, type_id: uuid.UUID, *, expected_version: int
) -> None:
    """Remove a tenant's own type: refused while CIs or types below use it (with counts)."""
    require_configure(subject)
    row = await get_type(session, type_id)
    if row.built_in:
        raise Conflict(code="cmdb_built_in_locked")
    cis = await session.scalar(
        select(func.count()).where(Ci.type_id == row.id, Ci.deleted_at.is_(None))
    )
    children = await session.scalar(
        select(func.count()).where(CiType.parent_id == row.id, CiType.deleted_at.is_(None))
    )
    if cis or children:
        raise Conflict(
            code="cmdb_ci_type_in_use",
            params={"ci_count": int(cis or 0), "type_count": int(children or 0)},
        )
    # Custom fields scoped to it (0175): its children are already refused above, so only its own.
    if fields := await metadata.fields_scoped_to(session, metadata.CustomFieldEntity.CI, [row.id]):
        raise Conflict(code="cmdb_ci_type_has_fields", params={"field_count": len(fields)})
    deleted = await TypeRepository(session).soft_delete(row.id, expected_version=expected_version)
    await _config_event(session, "type", "deleted", row.id, deleted.version)


# --- states ---------------------------------------------------------------------------------------


async def list_states(session: AsyncSession) -> list[CiState]:
    """Every live state, in order."""
    await ensure_defaults(session)
    return list(
        await session.scalars(
            select(CiState)
            .where(CiState.deleted_at.is_(None))
            .order_by(CiState.position, CiState.api_name)
        )
    )


async def get_state(session: AsyncSession, state_id: uuid.UUID) -> CiState:
    """A live state (404 `cmdb_ci_state_not_found`)."""
    await ensure_defaults(session)
    row = await session.scalar(
        select(CiState).where(CiState.id == state_id, CiState.deleted_at.is_(None))
    )
    if row is None:
        raise NotFound(code="cmdb_ci_state_not_found")
    return row


async def default_state(session: AsyncSession) -> CiState:
    """The state a new CI takes when none is given."""
    await ensure_defaults(session)
    found = await session.scalar(
        select(CiState).where(
            CiState.api_name == domain.DEFAULT_STATE, CiState.deleted_at.is_(None)
        )
    )
    return found or (await list_states(session))[0]


def _check_state(values: Mapping[str, Any], *, built_in: bool, creating: bool) -> None:
    problems: list[domain.Problem] = []
    if creating:
        api_name = values.get("api_name")
        if not isinstance(api_name, str) or not domain.API_NAME.fullmatch(api_name):
            problems.append(domain.Problem("api_name", "invalid_key"))
    if "names" in values or creating:
        problems += domain.names_problems(values.get("names"), required=not built_in)
    if "category" in values and values["category"] not in {c.value for c in domain.CiStateCategory}:
        problems.append(domain.Problem("category", "invalid_choice"))
    if problems:
        raise invalid(problems)


async def create_state(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any]
) -> CiState:
    """A tenant's own state."""
    require_configure(subject)
    await ensure_defaults(session)
    _check_state(values, built_in=False, creating=True)
    await _api_name_free(session, CiState, values["api_name"])
    row = CiState(
        id=new_id(),
        api_name=values["api_name"],
        built_in=False,
        names=dict(values["names"]),
        category=values.get("category", domain.CiStateCategory.ACTIVE.value),
        position=int(values.get("position", 100)),
    )
    await StateRepository(session).add(row)
    await _config_event(session, "state", "created", row.id, row.version)
    return row


async def update_state(
    session: AsyncSession,
    subject: Subject,
    state_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
) -> CiState:
    """Rename, reorder or re-categorise a state (a built-in state's category is fixed)."""
    require_configure(subject)
    row = await get_state(session, state_id)
    if row.built_in and "category" in values and values["category"] != row.category:
        raise Conflict(code="cmdb_built_in_locked")
    _check_state(values, built_in=row.built_in, creating=False)
    changes = {
        k: v
        for k, v in values.items()
        if k in {"names", "category", "position"} and getattr(row, k) != v
    }
    if not changes:
        if row.version != expected_version:
            raise await stale_version(session, row, expected_version=expected_version)
        return row
    updated = await StateRepository(session).update(
        row.id, expected_version=expected_version, changes=changes
    )
    await _config_event(session, "state", "updated", updated.id, updated.version)
    return updated


async def delete_state(
    session: AsyncSession, subject: Subject, state_id: uuid.UUID, *, expected_version: int
) -> None:
    """Remove a tenant's own state: refused while CIs hold it (with the count)."""
    require_configure(subject)
    row = await get_state(session, state_id)
    if row.built_in:
        raise Conflict(code="cmdb_built_in_locked")
    cis = await session.scalar(
        select(func.count()).where(Ci.state_id == row.id, Ci.deleted_at.is_(None))
    )
    if cis:
        raise Conflict(code="cmdb_ci_state_in_use", params={"ci_count": int(cis)})
    deleted = await StateRepository(session).soft_delete(row.id, expected_version=expected_version)
    await _config_event(session, "state", "deleted", row.id, deleted.version)


# --- settings -------------------------------------------------------------------------------------


async def get_settings(session: AsyncSession) -> CmdbSettings:
    """The tenant's CMDB settings."""
    await ensure_defaults(session)
    row: CmdbSettings | None = await session.scalar(select(CmdbSettings))
    if row is None:  # pragma: no cover - ensure_defaults made it
        raise NotFound(code="cmdb_ci_not_found")
    return row


async def update_settings(
    session: AsyncSession,
    subject: Subject,
    *,
    expected_version: int,
    exclude_eol_from_pickers: bool,
) -> CmdbSettings:
    """Change the settings (If-Match)."""
    require_configure(subject)
    row = await get_settings(session)
    if row.version != expected_version:
        raise await stale_version(session, row, expected_version=expected_version)
    if row.exclude_eol_from_pickers != exclude_eol_from_pickers:
        row.exclude_eol_from_pickers = exclude_eol_from_pickers
        row.version += 1
        row.updated_by = subject.user_id
        await session.flush()
        await _config_event(session, "settings", "updated", None, row.version)
    return row
