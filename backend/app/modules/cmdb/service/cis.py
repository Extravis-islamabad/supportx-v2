"""Configuration items (WP-053 S1; REQ-CMDB-002, 003, 005, 024 write side, 031).

Each write, in one transaction: the right and the record's scope, the domain rules, the row with
optimistic concurrency (If-Match), field history, a snapshot in `cmdb_ci_versions`, and the outbox
event. Scopes of `cmdb.view` (and the write rights): all, site (the CI's site), group (its owner
or managing group). `cmdb.manage`, reserved before S1, covers add, edit and delete.

Custom fields (0175 part 2) are metadata's, scoped to a CI type and the types below it: a save
checks them against the CI's type (`metadata.clean(type_id=…)`), history names them
`custom.<key>`, and ADR-047 rules hide, mask or lock them per role on every read and write. A
type change that would drop values outside the new type's fields needs
`confirm_dropped_fields`; history then names the dropped fields, never their values.

Attribute sources (S4a, REQ-CMDB-016): every save stamps the attributes it changed with their
source and time (`sources`): a person's save `hand`, a sync rule's `asset_sync`. A stamp is
never shown for a field the reader may not read (hidden, masked or sealed). The sync identity
writes through `sync_create` and `sync_update`, the same save path with no person's scope or
read-only rules (a system write, ADR-047 §8).
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed
from app.modules import assets, metadata
from app.modules.cmdb.domain import field_access as field_rules
from app.modules.cmdb.domain import sources as attribute_sources
from app.modules.cmdb.domain import types as domain
from app.modules.cmdb.domain.sources import AttributeSource, Stamp
from app.modules.cmdb.events import CiCreated, CiDeleted, CiRestored, CiUpdated
from app.modules.cmdb.infra.models import Ci, CiAlias, CiState, CiType
from app.modules.cmdb.service import ref_names
from app.modules.cmdb.service.catalogue import (
    ADD,
    DELETE,
    EDIT,
    MANAGE,
    VIEW,
    default_state,
    ensure_defaults,
    get_settings,
    get_state,
    get_type,
    invalid,
)
from app.modules.cmdb.service.snapshots import save_version
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

RECORD_TYPE = "ci"
DISPLAY_PREFIX = "CI"
FROM_ASSETS_MAX = 100
PICKER_MAX = 50
ENTITY = metadata.CustomFieldEntity.CI  # metadata's custom fields on CIs (0175)
DROPPED_FIELD = "fields_dropped"  # a type change's history line: the keys dropped, no values
# Fields a person edits (the type changes through its own action); custom values come as
# `custom`, checked by metadata.
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
)
SNAPSHOT = ("type_id", *EDITABLE, "asset_id", "source")
# Where a value came from when no save has stamped it yet (a CI from before 0191): its CI's own
# origin, so a sync never overwrites what a person typed before sources existed.
ORIGIN_SOURCE = {
    domain.CiSource.MANUAL.value: AttributeSource.HAND,
    domain.CiSource.ASSET_SYNC.value: AttributeSource.ASSET_SYNC,
    domain.CiSource.IMPORT.value: AttributeSource.IMPORT,
    domain.CiSource.MONETX.value: AttributeSource.MONETX,
}

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
    narrowed_as="ci",  # fine-grained access (ADR-053): applied inside scope_filter
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
    history_count: int
    can_edit: bool
    can_delete: bool
    # Custom values the person may read (ADR-047): hidden and masked ones are left out; masked
    # ones are named in `masked_fields`, and every field under a rule in `read_only_fields`.
    custom: dict[str, Any]
    masked_fields: tuple[str, ...]
    read_only_fields: tuple[str, ...]
    # The CI's references named for this reader (site, owner, groups, asset, person custom
    # fields), by the referenced ID; never an ID as a label (CMDB polish).
    names: dict[str, ref_names.RefName] = field(default_factory=dict)
    # Each attribute's source and time (REQ-CMDB-016), for the fields the reader may read.
    sources: dict[str, Stamp] = field(default_factory=dict)


async def _may(session: AsyncSession, subject: Subject, permission: str, ci_id: uuid.UUID) -> bool:
    key = (
        writer(subject, permission)
        if permission != VIEW
        else (VIEW if subject.holds(VIEW) else None)
    )
    if key is None:
        return False
    return bool(await authorize_stored(session, subject, key, CIS, Ci.id, ci_id))


def _unseen(subject: Subject) -> field_rules.Unseen:
    return field_rules.unseen(subject.field_access, RECORD_TYPE)


async def sealed_fields(session: AsyncSession) -> frozenset[str]:
    """Custom fields marked sensitive or under encryption (ADR-050): never a source shown."""
    return frozenset(
        f"{field_rules.CUSTOM}{m.key}"
        for m in await metadata.field_marks(session, ENTITY, retired=True)
        if m.sensitive or m.seal_state != metadata.PLAIN
    )


async def withheld(session: AsyncSession, subject: Subject) -> frozenset[str]:
    """The attributes whose source a reader may not see: hidden, masked or sealed."""
    return _unseen(subject).all | await sealed_fields(session)


def effective_stamps(record: Ci) -> dict[str, Stamp]:
    """Each attribute's stamp; a value no save has stamped counts as set by the CI's origin."""
    found = attribute_sources.stamps(record.sources)
    origin = ORIGIN_SOURCE.get(record.source, AttributeSource.HAND)
    held = field_rules.flat(snapshot(record))
    for attribute in (*EDITABLE, *(k for k in held if k.startswith(field_rules.CUSTOM))):
        if attribute not in found and held.get(attribute) is not None:
            found[attribute] = Stamp(origin, record.created_at)
    return found


def _stamp(
    record: Ci, before: Mapping[str, Any], after: Mapping[str, Any], source: AttributeSource
) -> dict[str, Any]:
    """`sources` after a save: the changed attributes stamped, dropped custom values unstamped."""
    old, new = field_rules.flat(before), field_rules.flat(after)
    changed = [
        k
        for k in sorted(set(old) | set(new))
        if (k in EDITABLE or k.startswith(field_rules.CUSTOM)) and old.get(k) != new.get(k)
    ]
    gone = [k for k in changed if k.startswith(field_rules.CUSTOM) and new.get(k) is None]
    kept = attribute_sources.unstamped(record.sources, gone)
    return attribute_sources.stamped(kept, [k for k in changed if k not in gone], source, _now())


async def _view(session: AsyncSession, subject: Subject, record: Ci) -> CiView:
    unseen = _unseen(subject)
    held = record.custom or {}
    custom = field_rules.without(held, unseen.custom_keys())
    # Only what the reader may read is named: hidden and masked custom values are left out.
    referred = {
        **{name: getattr(record, name) for name in ref_names.REFERENCE_FIELDS},
        **{f"{field_rules.CUSTOM}{key}": value for key, value in custom.items()},
    }
    hidden_sources = unseen.all | await sealed_fields(session)
    shown = {k: v for k, v in effective_stamps(record).items() if k not in hidden_sources}
    return CiView(
        record=record,
        sources=shown,
        history_count=await count_saves(session, RECORD_TYPE, record.id),
        can_edit=await _may(session, subject, EDIT, record.id),
        can_delete=await _may(session, subject, DELETE, record.id),
        names=await ref_names.names_for(session, subject, [referred]),
        custom=custom,
        masked_fields=tuple(
            sorted(f for f in unseen.masked if f.removeprefix(field_rules.CUSTOM) in held)
        ),
        read_only_fields=tuple(sorted(field_rules.read_only(subject.field_access, RECORD_TYPE))),
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
    shown = _mask_custom(_unseen(subject), entries)
    return await _mask_links(session, subject, shown), cursor, names


def _mask_custom(unseen: field_rules.Unseen, entries: list[HistoryEntry]) -> list[HistoryEntry]:
    """Withheld custom fields in the history too (ADR-047), as work items do.

    Hidden ones are left out; masked ones keep the line (that it changed, when, by whom) but never
    the values. A type change's dropped-fields line names keys only, so it stays, without the
    hidden ones.
    """
    if not unseen.all:
        return entries
    hidden_keys = {f.removeprefix(field_rules.CUSTOM) for f in unseen.hidden}

    def shown(change: Change) -> Change | None:
        if change.field in unseen.hidden:
            return None
        if change.field in unseen.masked:
            return replace(change, old=field_rules.MASKED, new=field_rules.MASKED)
        if change.field == DROPPED_FIELD and isinstance(change.new, list):
            keys = [
                k for k in change.new if str(k).removeprefix(field_rules.CUSTOM) not in hidden_keys
            ]
            return replace(change, new=keys) if keys else None
        return change

    out: list[HistoryEntry] = []
    for entry in entries:
        changes = [c for c in (shown(c) for c in entry.changes) if c is not None]
        out.append(replace(entry, changes=changes))
    return out


LINK_FIELD = "relationship"  # a relationship line's field (service/relationships.py)
# A merge's lines (service/merge.py, S4b): the other CI by ID only ({"ci_id"}), never its name.
MERGED_INTO = "merged_into"  # the merged CI's line
MERGED_FROM = "merged_from"  # the survivor's line
MERGE_LINES = frozenset({MERGED_INTO, MERGED_FROM})


def _linked(value: object) -> str | None:
    return str(value["ci_id"]) if isinstance(value, Mapping) and value.get("ci_id") else None


async def _mask_links(
    session: AsyncSession, subject: Subject, entries: list[HistoryEntry]
) -> list[HistoryEntry]:
    """Relationship lines name the other CI only when the reader may see it now.

    Otherwise the line says `restricted` with no ID (lane C's condition 2, as the map's
    placeholders).
    """
    masked_fields = {LINK_FIELD, *MERGE_LINES}
    linked = {
        i
        for e in entries
        for c in e.changes
        if c.field in masked_fields
        for i in (_linked(c.old), _linked(c.new))
        if i
    }
    if not linked:
        return entries
    asked = [uuid.UUID(i) for i in linked]
    seen = {
        str(i)
        for i in await session.scalars(
            visible_rows(subject).with_only_columns(Ci.id).where(Ci.id.in_(asked))
        )
    }
    # A merge line names a CI that may be in the trash (the merged one): seen if within reach.
    seen_any = seen | {
        str(i)
        for i in await session.scalars(
            select(Ci.id).where(Ci.id.in_(asked), scope_filter(subject, VIEW, CIS))
        )
    }

    def masked(value: Any, known: set[str]) -> Any:  # noqa: ANN401 - a history value (JSON)
        ci = _linked(value)
        if ci is None or ci in known:
            return value
        return {**value, "ci_id": None, "restricted": True}

    def shown(change: Change) -> Change:
        if change.field not in masked_fields:
            return change
        known = seen if change.field == LINK_FIELD else seen_any
        return replace(change, old=masked(change.old, known), new=masked(change.new, known))

    return [replace(e, changes=[shown(c) for c in e.changes]) for e in entries]


# --- writing --------------------------------------------------------------------------------------


def _json(value: object) -> Any:  # noqa: ANN401 - history and snapshots store JSON values
    return str(value) if isinstance(value, uuid.UUID) else value


def snapshot(record: Ci) -> dict[str, Any]:
    """The CI's saved fields as JSON (a version's snapshot), its custom values under `custom`."""
    found = {name: _json(getattr(record, name)) for name in SNAPSHOT}
    found["custom"] = dict(record.custom or {})
    return found


def _history_changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[Change]:
    """One history line per changed field, each custom value as its own `custom.<key>`."""
    old, new = field_rules.flat(before), field_rules.flat(after)
    return [
        Change(k, old.get(k), new.get(k))
        for k in [*new, *sorted(old.keys() - new.keys())]
        if old.get(k) != new.get(k)
    ]


async def _save_version(session: AsyncSession, record: Ci, subject: Subject | None) -> None:
    """Append the CI as it is now, with its relationships (REQ-CMDB-024; the app may only add).

    `subject` None: the sync identity's save (no person saved it).
    """
    await save_version(
        session, record, snapshot(record), subject.user_id if subject is not None else None
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


async def _custom(
    session: AsyncSession,
    sent: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
    type_id: uuid.UUID,
) -> dict[str, Any] | None:
    """The CI's custom values after this save (None: untouched), checked by metadata.

    `type_id`: the CI's type; a field scoped to another branch of the type tree is unknown to it
    (`unknown_field`, 0175). A new CI starts from the fields' defaults.
    """
    creating = current is None
    if sent is None and not creating:
        return None
    before = dict(current or {})
    cleaned, found = await metadata.clean(
        session,
        ENTITY,
        sent or {},
        current=before,
        creating=creating,
        defaults=creating,
        type_id=type_id,
    )
    if found:
        params = await metadata.problem_params(session, ENTITY, found)
        raise ValidationFailed(
            errors=[
                FieldError(
                    field=f"body.{path}",
                    code=code,
                    message_key=f"errors.field.{code}",
                    params=dict(params.get(path, {})),
                )
                for path, code in found
            ]
        )
    merged = {**before, **cleaned}
    return {k: v for k, v in merged.items() if v is not None}


def _require_writable(subject: Subject | None, changed: Sequence[str]) -> None:
    """403 `field_read_only` when a person changes a custom field their roles may only read.

    ADR-047 §8, as work items do: a form sending a read-only value back unchanged passes, and a
    service identity's writes (a connector's) are system writes.
    """
    if subject is None or not subject.person:
        return
    locked = field_rules.refused(changed, field_rules.read_only(subject.field_access, RECORD_TYPE))
    if locked:
        raise PermissionDenied(code="field_read_only", params={"field": locked[0]})


def _changed_custom(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    return [
        f"{field_rules.CUSTOM}{k}"
        for k in sorted(set(before) | set(after))
        if before.get(k) != after.get(k)
    ]


async def _add(  # noqa: PLR0913 - every part of a new CI, explicit
    session: AsyncSession,
    subject: Subject | None,
    values: Mapping[str, Any],
    source: Source,
    *,
    origin: domain.CiSource = domain.CiSource.MANUAL,
    asset_id: uuid.UUID | None = None,
    stamp_as: AttributeSource | None = None,
) -> Ci:
    """A new CI. `subject` None: the sync identity (no person's scope applies).

    Its set attributes are stamped `stamp_as`, else `hand` (a person's values; from-assets names
    a CI after its asset, so its name is the asset sync's).
    """
    problems = _check_codes(values)
    if "name" not in values:
        problems.append(domain.Problem("name", "required"))
    if values.get("type_id") is None:
        problems.append(domain.Problem("type_id", "required"))
    if problems:
        raise invalid(problems)
    ci_type = await get_type(session, values["type_id"])
    await _check_references(session, values)
    sent = values.get("custom")
    _require_writable(
        subject,
        [f"{field_rules.CUSTOM}{k}" for k, v in (sent or {}).items() if v is not None],
    )
    custom = await _custom(session, sent, None, ci_type.id) or {}
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
    record.sources = attribute_sources.stamped(
        {},
        [
            k
            for k, v in field_rules.flat(snapshot(record)).items()
            if v is not None and (k in EDITABLE or k.startswith(field_rules.CUSTOM))
        ],
        stamp_as or AttributeSource.HAND,
        _now(),
    )
    if asset_id is not None and stamp_as is None:
        record.sources = attribute_sources.stamped(
            record.sources, ["name"], AttributeSource.ASSET_SYNC, _now()
        )
    await CiRepository(session).add(record)
    if subject is not None:
        await _within_scope(session, subject, ADD, record.id)
    if custom:
        await metadata.mark_used(session, ENTITY, list(custom))
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="created",
        changes=_history_changes({}, snapshot(record)),
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


async def editable(session: AsyncSession, subject: Subject, ci_id: uuid.UUID) -> Ci:
    """The CI, if the person may edit it: 404 if they can't see it, 403 if they can't edit it.

    For a caller that decides what to write before calling `update` (an import's who wins):
    the per-CI edit check comes first, so a row that ends up writing nothing still tells a
    person nothing about a CI they may not edit (lane C's #577 re-check).
    """
    return await _writable(session, subject, EDIT, ci_id)


async def _save(  # noqa: PLR0913 - the record, the version and the change, explicit
    session: AsyncSession,
    subject: Subject | None,
    record: Ci,
    *,
    expected_version: int,
    columns: Mapping[str, Any],
    source: Source,
    extra: Sequence[Change] = (),
    quiet: frozenset[str] = frozenset(),
    stamp_as: AttributeSource = AttributeSource.HAND,
) -> Ci:
    """One update: version, history, snapshot, attribute sources, event.

    `extra`: history lines of the caller's own; `quiet`: fields whose values never go into the
    history (a type change's dropped custom values, named by key in `extra` instead).
    `subject` None: the sync identity (no person's scope applies); `stamp_as`: the source the
    changed attributes are stamped with.
    """
    before = snapshot(record)
    if columns:
        after = {**before, **{k: _json(v) for k, v in columns.items() if k != "custom"}}
        if "custom" in columns:
            after["custom"] = dict(columns["custom"] or {})
        columns = {**columns, "sources": _stamp(record, before, after, stamp_as)}
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
    if subject is not None:
        await _within_scope(session, subject, EDIT, updated.id)
    if "custom" in columns and updated.custom:
        await metadata.mark_used(session, ENTITY, list(updated.custom))
    changes = [
        *(c for c in _history_changes(before, snapshot(updated)) if c.field not in quiet),
        *extra,
    ]
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
    stamp_as: AttributeSource = AttributeSource.HAND,
) -> CiView:
    """Change the fields sent (If-Match). Unchanged input: no new version, no event.

    `stamp_as`: the source the changed attributes are stamped with (`hand` for a person's own
    edit; an import's rows say `import`).
    """
    record = await _writable(session, subject, EDIT, ci_id)
    draft = {k: v for k, v in values.items() if k in EDITABLE}
    if problems := _check_codes(draft):
        raise invalid(problems)
    await _check_references(session, {k: v for k, v in draft.items() if v != getattr(record, k)})
    if "name" in draft:
        draft["name"] = str(draft["name"]).strip()
    columns = {k: v for k, v in draft.items() if getattr(record, k) != v}
    held = dict(record.custom or {})
    custom = await _custom(session, values.get("custom"), held, record.type_id)
    if custom is not None and custom != held:
        _require_writable(subject, _changed_custom(held, custom))
        columns["custom"] = custom
    saved = await _save(
        session,
        subject,
        record,
        expected_version=expected_version,
        columns=columns,
        source=source,
        stamp_as=stamp_as,
    )
    return await _view(session, subject, saved)


@dataclass(frozen=True)
class DroppedField:
    """A custom field whose value a type change would drop: its key and the admin's names."""

    key: str
    labels: dict[str, str]


@dataclass(frozen=True)
class TypeChangePreview:
    """What moving a CI to a type would drop.

    `dropped`: the fields the person may see (a hidden one is never named). `blocked`: one of the
    dropped fields is under a field access rule for them, so they may not change the type.
    """

    dropped: list[DroppedField]
    blocked: bool


async def _dropped_keys(session: AsyncSession, record: Ci, type_id: uuid.UUID) -> list[str]:
    """Custom keys holding a value that the new type's fields do not include."""
    if record.type_id == type_id or not record.custom:
        return []
    kept = [
        f.key for f in await metadata.field_marks(session, ENTITY, retired=True, type_id=type_id)
    ]
    known = [f.key for f in await metadata.field_marks(session, ENTITY, retired=True)]
    return field_rules.dropped(record.custom, kept, known)


def _locked(subject: Subject, keys: Sequence[str]) -> list[str]:
    if not subject.person:
        return []
    return field_rules.refused(
        [f"{field_rules.CUSTOM}{k}" for k in keys],
        field_rules.read_only(subject.field_access, RECORD_TYPE),
    )


async def type_change_preview(
    session: AsyncSession, subject: Subject, ci_id: uuid.UUID, type_id: uuid.UUID
) -> TypeChangePreview:
    """The custom values moving the CI to `type_id` would drop (nothing is changed)."""
    record = await _writable(session, subject, EDIT, ci_id)
    await get_type(session, type_id)
    keys = await _dropped_keys(session, record, type_id)
    hidden = _unseen(subject).hidden
    marks = {f.key: f for f in await metadata.field_marks(session, ENTITY, retired=True)}
    return TypeChangePreview(
        dropped=[
            DroppedField(k, dict(marks[k].labels))
            for k in keys
            if f"{field_rules.CUSTOM}{k}" not in hidden and k in marks
        ],
        blocked=bool(_locked(subject, keys)),
    )


async def change_type(  # noqa: PLR0913 - the record, the version and the change, explicit
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    *,
    type_id: uuid.UUID,
    expected_version: int,
    source: Source,
    confirm_dropped_fields: bool = False,
) -> CiView:
    """Move the CI to another live type (REQ-CMDB-003).

    Custom values outside the new type's fields (0175) are dropped only with
    `confirm_dropped_fields` (409 `cmdb_ci_type_change_drops_fields` otherwise, with the count),
    and only when none of them is under a field access rule for the person (403
    `field_read_only`). History names the dropped fields by key, never their values (lane A's
    note 2).
    """
    record = await _writable(session, subject, EDIT, ci_id)
    await get_type(session, type_id)
    columns: dict[str, Any] = {} if record.type_id == type_id else {"type_id": type_id}
    keys = await _dropped_keys(session, record, type_id)
    extra: list[Change] = []
    quiet: frozenset[str] = frozenset()
    if keys:
        if locked := _locked(subject, keys):
            raise PermissionDenied(code="field_read_only", params={"field": locked[0]})
        if not confirm_dropped_fields:
            raise Conflict(
                code="cmdb_ci_type_change_drops_fields", params={"field_count": len(keys)}
            )
        named = [f"{field_rules.CUSTOM}{k}" for k in keys]
        columns["custom"] = {k: v for k, v in (record.custom or {}).items() if k not in keys}
        extra = [Change(DROPPED_FIELD, None, named)]
        quiet = frozenset(named)
    saved = await _save(
        session,
        subject,
        record,
        expected_version=expected_version,
        columns=columns,
        source=source,
        extra=extra,
        quiet=quiet,
    )
    return await _view(session, subject, saved)


async def copy(session: AsyncSession, subject: Subject, ci_id: uuid.UUID, source: Source) -> CiView:
    """A new CI with the same type and fields (never the asset link)."""
    if writer(subject, ADD) is None:
        raise _denied(ADD)
    original = await _visible(session, subject, ci_id)
    values: dict[str, Any] = {k: getattr(original, k) for k in ("type_id", *EDITABLE)}
    # Only custom values the person could set themselves are copied: a field under any of their
    # rules (hidden, masked or read-only, ADR-047) never travels, so the copy is never refused.
    locked = field_rules.read_only(subject.field_access, RECORD_TYPE)
    values["custom"] = field_rules.without(
        original.custom,
        frozenset(f.removeprefix(field_rules.CUSTOM) for f in locked),
    )
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


async def restore(  # noqa: PLR0913 - the record, its version, the source and the warning
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
    confirm_merged: bool = False,
) -> CiView:
    """Take out of the trash, exactly as it was (refused if its asset has a new CI since).

    A CI merged into another (S4b) comes back only once the person has seen the warning (409
    `cmdb_ci_restore_merged`; then `confirm_merged`). It comes back on its own: the alias ends and
    nothing moves back (lane C (10)). The warning names the survivor only to a reader who may see
    it.
    """
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
    alias: CiAlias | None = await session.scalar(
        select(CiAlias)
        .where(
            CiAlias.alias_id == record.id,
            CiAlias.restored_at.is_(None),
            CiAlias.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if alias is not None and not confirm_merged:
        survivor = await session.scalar(visible_rows(subject).where(Ci.id == alias.ci_id))
        params = {"display_id": survivor.display_id} if survivor is not None else {}
        raise Conflict(code="cmdb_ci_restore_merged", params=params)
    if alias is not None:
        alias.restored_at, alias.restored_by = _now(), subject.user_id
        alias.version += 1
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


# --- the sync identity (WP-053 S4a, REQ-CMDB-015) ----------------------------------------------


async def ci_of_asset(session: AsyncSession, asset_id: uuid.UUID) -> Ci | None:
    """The live CI of an asset (one at most), locked for the sync's save; read as the system."""
    found: Ci | None = await session.scalar(
        select(Ci).where(Ci.asset_id == asset_id, Ci.deleted_at.is_(None)).with_for_update()
    )
    return found


async def sync_create(
    session: AsyncSession,
    values: Mapping[str, Any],
    *,
    asset_id: uuid.UUID,
    source: Source,
) -> Ci:
    """A new CI for an asset, by the sync identity: the ordinary checks, history and event.

    No person's scope or read-only rules apply (a system write, ADR-047 §8); its attributes are
    stamped `asset_sync`.
    """
    await ensure_defaults(session)
    return await _add(
        session,
        None,
        values,
        source,
        origin=domain.CiSource.ASSET_SYNC,
        asset_id=asset_id,
        stamp_as=AttributeSource.ASSET_SYNC,
    )


async def sync_update(
    session: AsyncSession, record: Ci, changes: Mapping[str, Any], *, source: Source
) -> Ci:
    """Change a CI's attributes by the sync identity (core fields and `custom.<key>` values).

    The same save as a person's (checks, metadata's custom rules, history, version, event), with
    the changed attributes stamped `asset_sync`. The caller decided what wins (domain/sync.py).
    """
    core = {k: v for k, v in changes.items() if k in EDITABLE}
    if problems := _check_codes(core):
        raise invalid(problems)
    await _check_references(session, {k: v for k, v in core.items() if v != getattr(record, k)})
    columns: dict[str, Any] = {k: v for k, v in core.items() if getattr(record, k) != v}
    sent = {
        k.removeprefix(field_rules.CUSTOM): v
        for k, v in changes.items()
        if k.startswith(field_rules.CUSTOM)
    }
    if sent:
        held = dict(record.custom or {})
        custom = await _custom(session, sent, held, record.type_id)
        if custom is not None and custom != held:
            columns["custom"] = custom
    return await _save(
        session,
        None,
        record,
        expected_version=record.version,
        columns=columns,
        source=source,
        stamp_as=AttributeSource.ASSET_SYNC,
    )


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
            # The caller chose these IDs: an asset outside their reach and one that exists nowhere
            # read the same, so the answer never confirms that an unseen asset exists (lane B's
            # write walk, lane C's re-check, 2026-11-20). `gone` stays in the schema, unused here.
            skipped.append((ref.id, "hidden"))
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
        # A merged CI's display ID finds its survivor (S4b), within the reader's scope above.
        alias = Ci.id.in_(
            select(CiAlias.ci_id).where(
                CiAlias.restored_at.is_(None),
                CiAlias.deleted_at.is_(None),
                func.lower(CiAlias.alias_display_id) == search.strip().lower(),
            )
        )
        rows = rows.where(
            or_(Ci.name.ilike(term, escape="\\"), Ci.display_id.ilike(term, escape="\\"), alias)
        )
    rows = rows.order_by(func.lower(Ci.name), Ci.id).limit(max(1, min(limit, PICKER_MAX)))
    return list(await session.scalars(rows))


# --- for merges (service/merge.py, S4b) -----------------------------------------------------------


def not_found() -> NotFound:
    """The one answer for a CI the person may not see, or that exists nowhere."""
    return NotFound(code="cmdb_ci_not_found")


async def get_visible(session: AsyncSession, subject: Subject, ci_id: uuid.UUID) -> Ci:
    """A live CI the person may see (404 otherwise)."""
    return await _visible(session, subject, ci_id)


def json_value(value: object) -> Any:  # noqa: ANN401 - a field's JSON value
    """A field's value as history and previews show it (IDs as text)."""
    return _json(value)


def withheld_custom(subject: Subject) -> frozenset[str]:
    """Custom field keys the person may not read on CIs: hidden or masked (ADR-047, ADR-050)."""
    return frozenset(_unseen(subject).custom_keys())


async def stale(
    session: AsyncSession, ci_id: uuid.UUID, expected_version: int, current_version: int
) -> Conflict:
    """409 `version_conflict` explaining who changed what since `expected_version`."""
    return await _conflict(
        session,
        Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": current_version},
        ),
        ci_id,
    )


async def view(session: AsyncSession, subject: Subject, record: Ci) -> CiView:
    """The CI as the person may see it."""
    return await _view(session, subject, record)


async def save_merged(  # noqa: PLR0913 - the survivor, its new values and the merge's line
    session: AsyncSession,
    subject: Subject,
    record: Ci,
    *,
    columns: Mapping[str, Any],
    source: Source,
    extra: Sequence[Change],
) -> Ci:
    """The survivor of a merge: the chosen values through the ordinary save, with the merge line.

    With no value to change, the survivor still gets a version holding the "merged from" line.
    """
    if columns:
        return await _save(
            session,
            subject,
            record,
            expected_version=record.version,
            columns=columns,
            source=source,
            extra=extra,
        )
    record.version += 1
    record.updated_at, record.updated_by = _now(), subject.user_id
    await session.flush()
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="updated",
        changes=list(extra),
        source=source,
    )
    await _save_version(session, record, subject)
    await record_event(
        session,
        CiUpdated(ci_id=record.id, type_id=record.type_id, changed_fields=[c.field for c in extra]),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    return record


async def add_imported(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], source: Source
) -> Ci:
    """A new CI from an import row (S4b): the ordinary create, its attributes stamped `import`."""
    if writer(subject, ADD) is None:
        raise _denied(ADD)
    return await _add(
        session,
        subject,
        values,
        source,
        origin=domain.CiSource.IMPORT,
        stamp_as=AttributeSource.IMPORT,
    )
