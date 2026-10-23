"""Announcement use cases (WP-012): every write owns its transaction's rules.

Each write, in one transaction: check the permission and the record's scope (WP-016), apply the
domain rule, update the row with optimistic concurrency (If-Match), write the field history, write
the outbox event. Reads come in two kinds:

* **staff** (`announcements.view`, scope-filtered): everything, drafts and archive included;
* **audience** (any signed-in user): only what is published, inside its window and addressed to
  them (everyone, their sites, their groups). Anything else is 404, never 403, so a requester
  cannot even learn that a draft exists.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    Conflict,
    FieldError,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from app.modules.announcements.domain.announcement import (
    AUDIENCE_MAX,
    BODY_MAX,
    MACHINE,
    REASON_ACTIONS,
    REASON_MAX,
    TITLE_MAX,
    AnnouncementAction,
    AnnouncementAudience,
    AnnouncementSeverity,
    AnnouncementStatus,
    Window,
    next_change,
    publish_problems,
    visibility,
)
from app.modules.announcements.events import (
    AnnouncementCreated,
    AnnouncementDeleted,
    AnnouncementRestored,
    AnnouncementSettingsChanged,
    AnnouncementStatusChanged,
    AnnouncementUpdated,
)
from app.modules.announcements.infra.models import (
    Announcement,
    AnnouncementGroup,
    AnnouncementSettings,
    AnnouncementSite,
)
from app.modules.identity_access import (
    RecordFacts,
    ResourceType,
    SodRule,
    Subject,
    authorize,
    authorize_stored,
    display_names,
    require,
    scope_filter,
    user_names,
)
from app.modules.organization import existing_unit_ids
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.api.listing import ListQuery, PageResult, paginate
from app.shared.db.display_ids import next_display_id
from app.shared.db.repository import Repository
from app.shared.domain import InvalidTransition
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

RECORD_TYPE = "announcement"
DISPLAY_PREFIX = "ANN"
VIEW = "announcements.view"
MANAGE = "announcements.manage"
PUBLISH = "announcements.publish"
# Why a status action is disabled for this user right now (besides the publish rules and the
# policy layer's own reasons); the UI labels them as `action_reason.<code>`.
NOT_FROM_STATUS = "not_from_status"
NO_PERMISSION = "no_permission"
EDITABLE = (
    "title",
    "body",
    "severity",
    "audience",
    "site_ids",
    "group_ids",
    "show_as_banner",
    "publish_from",
    "publish_until",
    "owner_id",
)

ANNOUNCEMENT_FIELDS = ResourceFields(
    name="announcements",
    fields={
        "id": FilterField(Announcement.id, FieldType.UUID),
        "display_id": FilterField(Announcement.display_id, FieldType.STRING, sortable=True),
        "title": FilterField(Announcement.title, FieldType.STRING, sortable=True),
        "status": FilterField(
            Announcement.status,
            FieldType.ENUM,
            values=frozenset(s.value for s in AnnouncementStatus),
        ),
        "severity": FilterField(
            Announcement.severity,
            FieldType.ENUM,
            values=frozenset(s.value for s in AnnouncementSeverity),
        ),
        "audience": FilterField(
            Announcement.audience,
            FieldType.ENUM,
            values=frozenset(a.value for a in AnnouncementAudience),
        ),
        "owner_id": FilterField(Announcement.owner_id, FieldType.UUID),
        "show_as_banner": FilterField(Announcement.show_as_banner, FieldType.BOOLEAN),
        "created_at": FilterField(
            Announcement.created_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        "updated_at": FilterField(
            Announcement.updated_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        "published_at": FilterField(
            Announcement.published_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        "publish_from": FilterField(Announcement.publish_from, FieldType.DATETIME, simple=False),
        "publish_until": FilterField(Announcement.publish_until, FieldType.DATETIME, simple=False),
    },
    id_column=Announcement.id,
    default_sort=("-updated_at",),
)


def _in_sites(site_ids: frozenset[uuid.UUID]) -> ColumnElement[bool]:
    return Announcement.id.in_(
        select(AnnouncementSite.announcement_id).where(AnnouncementSite.site_id.in_(site_ids))
    )


def _in_groups(group_ids: frozenset[uuid.UUID]) -> ColumnElement[bool]:
    return Announcement.id.in_(
        select(AnnouncementGroup.announcement_id).where(AnnouncementGroup.group_id.in_(group_ids))
    )


def _own_record(subject: Subject, record: RecordFacts) -> bool:
    """Four-eyes: with the tenant setting on, the owner or author may not publish it."""
    return bool(record.attributes.get("require_second_publisher")) and (
        subject.user_id in record.owner_ids
    )


ANNOUNCEMENTS = ResourceType(
    name="announcements",
    fields=ANNOUNCEMENT_FIELDS,
    # own = you own it or wrote it; site / group = it is addressed to one of your sites / groups.
    owner_columns=(Announcement.owner_id, Announcement.created_by),
    site_scope=_in_sites,
    group_scope=_in_groups,
    sod_rules={PUBLISH: (SodRule("four_eyes", _own_record),)},
)


class AnnouncementRepository(Repository[Announcement]):
    """Announcements of the session's tenant."""

    model = Announcement


# --- views ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionState:
    """One status action as this user may use it now (disabled ones carry the reason)."""

    action: str
    allowed: bool
    reason: str | None = None


@dataclass(frozen=True)
class AnnouncementView:
    """Everything staff see about one announcement."""

    record: Announcement
    site_ids: list[uuid.UUID]
    group_ids: list[uuid.UUID]
    visibility: str
    next_change_in_seconds: float | None
    actions: list[ActionState] = field(default_factory=list)
    history_count: int = 0
    can_manage: bool = False


@dataclass(frozen=True)
class PublicView:
    """What its audience sees (no owner, audience details or workflow)."""

    record: Announcement
    visibility: str
    next_change_in_seconds: float | None


@dataclass(frozen=True)
class Feed:
    """What is on this user's screens now, and how long until that changes by the clock."""

    items: list[Announcement]
    next_change_in_seconds: float | None


def _now() -> datetime:
    return datetime.now(UTC)


def _seconds_until(moment: datetime | None, now: datetime) -> float | None:
    return None if moment is None else round(max(0.0, (moment - now).total_seconds()), 3)


# --- reading --------------------------------------------------------------------------------------


def _audience_includes(subject: Subject) -> ColumnElement[bool]:
    parts: list[ColumnElement[bool]] = [Announcement.audience == AnnouncementAudience.EVERYONE]
    if subject.site_ids:
        parts.append(
            and_(Announcement.audience == AnnouncementAudience.SITES, _in_sites(subject.site_ids))
        )
    if subject.group_ids:
        parts.append(
            and_(
                Announcement.audience == AnnouncementAudience.GROUPS, _in_groups(subject.group_ids)
            )
        )
    return or_(*parts)


def live_for(subject: Subject, now: datetime) -> ColumnElement[bool]:
    """Published, inside its window, addressed to the subject: what their screens show."""
    return and_(
        Announcement.deleted_at.is_(None),
        Announcement.status == AnnouncementStatus.PUBLISHED,
        or_(Announcement.publish_from.is_(None), Announcement.publish_from <= now),
        or_(Announcement.publish_until.is_(None), Announcement.publish_until > now),
        _audience_includes(subject),
    )


async def _units(
    session: AsyncSession, announcement_id: uuid.UUID
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    sites = await session.scalars(
        select(AnnouncementSite.site_id)
        .where(AnnouncementSite.announcement_id == announcement_id)
        .order_by(AnnouncementSite.site_id)
    )
    groups = await session.scalars(
        select(AnnouncementGroup.group_id)
        .where(AnnouncementGroup.announcement_id == announcement_id)
        .order_by(AnnouncementGroup.group_id)
    )
    return list(sites), list(groups)


async def _settings(session: AsyncSession) -> AnnouncementSettings | None:
    return await session.scalar(select(AnnouncementSettings))


async def _facts(session: AsyncSession, record: Announcement) -> RecordFacts:
    settings = await _settings(session)
    owners = frozenset(u for u in (record.owner_id, record.created_by) if u is not None)
    return RecordFacts(
        owner_ids=owners,
        attributes={
            "require_second_publisher": bool(settings and settings.require_second_publisher)
        },
    )


async def _staff_may(
    session: AsyncSession, subject: Subject, permission: str, record_id: uuid.UUID
) -> bool:
    if not subject.holds(permission):
        return False
    return bool(
        await authorize_stored(
            session, subject, permission, ANNOUNCEMENTS, Announcement.id, record_id
        )
    )


async def _action_states(
    session: AsyncSession, subject: Subject, record: Announcement, units: int
) -> list[ActionState]:
    """Every action in the fixed order; disabled ones say why (UI: disabled, not hidden)."""
    allowed_now = set(MACHINE.actions_from(record.status))
    may_manage = await _staff_may(session, subject, MANAGE, record.id)
    may_publish = await _staff_may(session, subject, PUBLISH, record.id)
    facts = await _facts(session, record)
    states: list[ActionState] = []
    for action in MACHINE.actions:
        if action not in allowed_now:
            states.append(ActionState(action, allowed=False, reason=NOT_FROM_STATUS))
            continue
        if action == AnnouncementAction.PUBLISH:
            if not may_publish:
                states.append(ActionState(action, allowed=False, reason=NO_PERMISSION))
                continue
            decision = authorize(subject, PUBLISH, ANNOUNCEMENTS, facts)
            if not decision:
                states.append(ActionState(action, allowed=False, reason=decision.reason))
                continue
            problems = publish_problems(
                title=record.title,
                body=record.body,
                audience=record.audience,
                units=units,
                window=Window(record.publish_from, record.publish_until),
                now=_now(),
            )
            if problems:
                states.append(ActionState(action, allowed=False, reason=problems[0]))
                continue
        elif not may_manage:
            states.append(ActionState(action, allowed=False, reason=NO_PERMISSION))
            continue
        states.append(ActionState(action, allowed=True))
    return states


async def _view(session: AsyncSession, subject: Subject, record: Announcement) -> AnnouncementView:
    now = _now()
    sites, groups = await _units(session, record.id)
    window = Window(record.publish_from, record.publish_until)
    return AnnouncementView(
        record=record,
        site_ids=sites,
        group_ids=groups,
        visibility=visibility(record.status, window, now),
        next_change_in_seconds=_seconds_until(next_change(record.status, window, now), now),
        actions=await _action_states(session, subject, record, len(sites) + len(groups)),
        history_count=await count_saves(session, RECORD_TYPE, record.id),
        can_manage=await _staff_may(session, subject, MANAGE, record.id),
    )


def staff_rows(subject: Subject, *, trash: bool = False) -> Select[Any]:
    """Announcements the subject may see as staff (scope-filtered)."""
    deleted = Announcement.deleted_at.is_not(None) if trash else Announcement.deleted_at.is_(None)
    return select(Announcement).where(deleted, scope_filter(subject, VIEW, ANNOUNCEMENTS))


async def list_announcements(
    session: AsyncSession, subject: Subject, query: ListQuery, *, trash: bool = False
) -> tuple[PageResult[Announcement], float | None]:
    """One page for staff, plus seconds until the first item on it changes visibility."""
    page = await paginate(session, staff_rows(subject, trash=trash), query)
    now = _now()
    moments = [
        moment
        for row in page.rows
        if (moment := next_change(row.status, Window(row.publish_from, row.publish_until), now))
    ]
    return page, _seconds_until(min(moments) if moments else None, now)


async def get_announcement(
    session: AsyncSession, subject: Subject, announcement_id: uuid.UUID
) -> AnnouncementView | PublicView:
    """Staff view within the subject's scope; else the audience view if it is live for them.

    Anything else, including drafts, archived, out-of-audience and out-of-window: 404.
    """
    record = await session.scalar(
        select(Announcement).where(
            Announcement.id == announcement_id, Announcement.deleted_at.is_(None)
        )
    )
    if record is not None and await _staff_may(session, subject, VIEW, record.id):
        return await _view(session, subject, record)
    now = _now()
    live = await session.scalar(
        select(Announcement).where(Announcement.id == announcement_id, live_for(subject, now))
    )
    if live is None:
        raise NotFound(code="announcement_not_found")
    window = Window(live.publish_from, live.publish_until)
    return PublicView(
        record=live,
        visibility=visibility(live.status, window, now),
        next_change_in_seconds=_seconds_until(next_change(live.status, window, now), now),
    )


async def feed(session: AsyncSession, subject: Subject, *, limit: int = 50) -> Feed:
    """What is live for the subject now (newest first) and when that changes next.

    The "next change" also counts announcements addressed to the subject that are published but
    not live yet: only the time leaks, never which announcement.
    """
    now = _now()
    items = list(
        await session.scalars(
            select(Announcement)
            .where(live_for(subject, now))
            .order_by(Announcement.published_at.desc(), Announcement.id.desc())
            .limit(limit)
        )
    )
    upcoming = and_(
        Announcement.deleted_at.is_(None),
        Announcement.status == AnnouncementStatus.PUBLISHED,
        _audience_includes(subject),
    )
    starts = await session.scalar(
        select(Announcement.publish_from)
        .where(upcoming, Announcement.publish_from > now)
        .order_by(Announcement.publish_from)
        .limit(1)
    )
    ends = await session.scalar(
        select(Announcement.publish_until)
        .where(live_for(subject, now), Announcement.publish_until.is_not(None))
        .order_by(Announcement.publish_until)
        .limit(1)
    )
    moments = [m for m in (starts, ends) if m is not None]
    return Feed(items, _seconds_until(min(moments) if moments else None, now))


async def history(
    session: AsyncSession,
    subject: Subject,
    announcement_id: uuid.UUID,
    *,
    before_version: int | None,
    limit: int,
) -> tuple[list[HistoryEntry], int | None, dict[str, str]]:
    """Saves of an announcement the subject may see as staff; plus actor names."""
    if not await _staff_may(session, subject, VIEW, announcement_id):
        raise NotFound(code="announcement_not_found")
    entries, cursor = await history_page(
        session, RECORD_TYPE, announcement_id, before_version=before_version, limit=limit
    )
    actor_ids = sorted({e.actor_id for e in entries if e.actor_id})
    found = await user_names(session, actor_ids)
    return entries, cursor, found


# --- writing --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Draft:
    """Validated input of a create or an edit (only the fields that were sent, for edits)."""

    values: dict[str, Any]


def _check(values: Mapping[str, Any], *, creating: bool) -> Draft:  # noqa: C901, PLR0912 - one rule per field, flat
    # FieldError(...) written out for every code, so the label check (tests/test_error_labels.py)
    # finds each one in the source.
    errors: list[FieldError] = []
    clean: dict[str, Any] = {}
    for name, value in values.items():
        at = f"body.{name}"
        if name not in EDITABLE:
            errors.append(
                FieldError(field=at, code="read_only", message_key="errors.field.read_only")
            )
        elif name in {"title", "body"}:
            text = (value or "").strip() if isinstance(value, str) else ""
            limit = TITLE_MAX if name == "title" else BODY_MAX
            if not text:
                errors.append(
                    FieldError(field=at, code="required", message_key="errors.field.required")
                )
            elif len(text) > limit:
                errors.append(
                    FieldError(
                        field=at,
                        code="value_too_long",
                        message_key="errors.field.value_too_long",
                        params={"max_length": limit},
                    )
                )
            else:
                clean[name] = text if name == "title" else value.replace("\r\n", "\n").strip()
        elif name in {"site_ids", "group_ids"}:
            ids = list(dict.fromkeys(value or []))
            if len(ids) > AUDIENCE_MAX:
                errors.append(
                    FieldError(
                        field=at,
                        code="too_many",
                        message_key="errors.field.too_many",
                        params={"max": AUDIENCE_MAX},
                    )
                )
            else:
                clean[name] = ids
        elif value is None and name in {"severity", "audience", "show_as_banner", "owner_id"}:
            errors.append(
                FieldError(field=at, code="required", message_key="errors.field.required")
            )
        else:
            clean[name] = value
    if creating:
        errors += [
            FieldError(field=f"body.{name}", code="required", message_key="errors.field.required")
            for name in ("title", "body")
            if name not in values
        ]
    if errors:
        raise ValidationFailed(errors=errors)
    return Draft(clean)


async def _check_references(
    session: AsyncSession,
    audience: str,
    site_ids: list[uuid.UUID],
    group_ids: list[uuid.UUID],
    owner_id: uuid.UUID | None,
) -> None:
    """Sites, groups and the owner must exist in this tenant; the audience must match its units."""
    errors: list[FieldError] = []
    if owner_id is not None and str(owner_id) not in await user_names(session, [str(owner_id)]):
        errors.append(
            FieldError(
                field="body.owner_id",
                code="unknown_value",
                message_key="errors.field.unknown_value",
            )
        )
    for name, kind, ids in (("site_ids", "site", site_ids), ("group_ids", "group", group_ids)):
        known = await existing_unit_ids(session, kind, ids)  # type: ignore[arg-type]  # Literal kind
        if set(ids) - known:
            errors.append(
                FieldError(
                    field=f"body.{name}",
                    code="unknown_value",
                    message_key="errors.field.unknown_value",
                )
            )
    if audience == AnnouncementAudience.SITES and group_ids:
        errors.append(
            FieldError(
                field="body.group_ids", code="not_allowed", message_key="errors.field.not_allowed"
            )
        )
    if audience == AnnouncementAudience.GROUPS and site_ids:
        errors.append(
            FieldError(
                field="body.site_ids", code="not_allowed", message_key="errors.field.not_allowed"
            )
        )
    if audience == AnnouncementAudience.EVERYONE and (site_ids or group_ids):
        errors.append(
            FieldError(
                field="body.audience", code="not_allowed", message_key="errors.field.not_allowed"
            )
        )
    if errors:
        raise ValidationFailed(errors=errors)


async def _replace_units(
    session: AsyncSession,
    record: Announcement,
    site_ids: list[uuid.UUID],
    group_ids: list[uuid.UUID],
) -> None:
    await session.execute(
        delete(AnnouncementSite).where(AnnouncementSite.announcement_id == record.id)
    )
    await session.execute(
        delete(AnnouncementGroup).where(AnnouncementGroup.announcement_id == record.id)
    )
    session.add_all(
        [
            *(
                AnnouncementSite(tenant_id=record.tenant_id, announcement_id=record.id, site_id=s)
                for s in site_ids
            ),
            *(
                AnnouncementGroup(tenant_id=record.tenant_id, announcement_id=record.id, group_id=g)
                for g in group_ids
            ),
        ]
    )
    await session.flush()


def _json(value: Any) -> Any:  # noqa: ANN401 - field values of several types
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list):
        return sorted(str(v) for v in value)
    return value


def _snapshot(
    record: Announcement, sites: list[uuid.UUID], groups: list[uuid.UUID]
) -> dict[str, Any]:
    return {
        "title": record.title,
        "body": record.body,
        "severity": record.severity,
        "audience": record.audience,
        "site_ids": _json(sites),
        "group_ids": _json(groups),
        "show_as_banner": record.show_as_banner,
        "publish_from": _json(record.publish_from),
        "publish_until": _json(record.publish_until),
        "owner_id": _json(record.owner_id),
    }


async def _within_scope(
    session: AsyncSession, subject: Subject, permission: str, record_id: uuid.UUID
) -> None:
    """A write must leave the record inside the writer's scope (no moving it out of reach)."""
    require(
        await authorize_stored(
            session, subject, permission, ANNOUNCEMENTS, Announcement.id, record_id
        ),
        permission,
    )


async def _names(session: AsyncSession, ids: Sequence[str]) -> list[str]:
    return await display_names(session, ids)


async def _conflict(session: AsyncSession, error: Conflict, record_id: uuid.UUID) -> Conflict:
    return await explain_conflict(
        session,
        error,
        record_type=RECORD_TYPE,
        record_id=record_id,
        names=lambda ids: _names(session, ids),
    )


async def create(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], source: Source
) -> AnnouncementView:
    """A new draft. The writer must be able to manage it afterwards (scope)."""
    if not subject.holds(MANAGE):
        raise PermissionDenied(params={"permission": MANAGE, "reason": NO_PERMISSION})
    draft = _check(values, creating=True).values
    audience = draft.get("audience", AnnouncementAudience.EVERYONE)
    sites = draft.get("site_ids", [])
    groups = draft.get("group_ids", [])
    await _check_references(session, audience, sites, groups, draft.get("owner_id"))
    window = Window(draft.get("publish_from"), draft.get("publish_until"))
    if window.problems():
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.publish_until",
                    code="window_end_before_start",
                    message_key="errors.field.window_end_before_start",
                )
            ]
        )
    record = Announcement(
        display_id=await next_display_id(session, DISPLAY_PREFIX),
        title=draft["title"],
        body=draft["body"],
        severity=draft.get("severity", AnnouncementSeverity.INFO),
        status=AnnouncementStatus.DRAFT,
        audience=audience,
        owner_id=draft.get("owner_id") or subject.user_id,
        show_as_banner=bool(draft.get("show_as_banner", False)),
        publish_from=window.publish_from,
        publish_until=window.publish_until,
    )
    await AnnouncementRepository(session).add(record)
    await _replace_units(session, record, sites, groups)
    await _within_scope(session, subject, MANAGE, record.id)
    after = _snapshot(record, sites, groups)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="created",
        changes=[Change(name, None, value) for name, value in after.items()],
        source=source,
    )
    await record_event(
        session,
        AnnouncementCreated(announcement_id=record.id, status=record.status),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    return await _view(session, subject, record)


async def _staff_record(
    session: AsyncSession, subject: Subject, permission: str, announcement_id: uuid.UUID
) -> Announcement:
    """The record for a staff write: 404 if not visible to the subject, 403 if visible only."""
    record = await session.scalar(
        select(Announcement).where(
            Announcement.id == announcement_id, Announcement.deleted_at.is_(None)
        )
    )
    if record is None or not await _staff_may(session, subject, VIEW, announcement_id):
        raise NotFound(code="announcement_not_found")
    await _within_scope(session, subject, permission, announcement_id)
    return record


async def update(  # noqa: PLR0913 - the record, the version and the change, explicit
    session: AsyncSession,
    subject: Subject,
    announcement_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
) -> AnnouncementView:
    """Edit fields (never the status). Unchanged input: no new version, no event."""
    record = await _staff_record(session, subject, MANAGE, announcement_id)
    sites, groups = await _units(session, record.id)
    draft = _check(values, creating=False).values
    before = _snapshot(record, sites, groups)
    new_sites = draft.pop("site_ids", sites)
    new_groups = draft.pop("group_ids", groups)
    audience = draft.get("audience", record.audience)
    await _check_references(session, audience, new_sites, new_groups, draft.get("owner_id"))
    window = Window(
        draft.get("publish_from", record.publish_from),
        draft.get("publish_until", record.publish_until),
    )
    if window.problems():
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.publish_until",
                    code="window_end_before_start",
                    message_key="errors.field.window_end_before_start",
                )
            ]
        )
    columns = {name: value for name, value in draft.items() if getattr(record, name) != value}
    units_changed = sorted(map(str, new_sites)) != sorted(map(str, sites)) or sorted(
        map(str, new_groups)
    ) != sorted(map(str, groups))
    if not columns and not units_changed:
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
        return await _view(session, subject, record)
    try:
        updated = await AnnouncementRepository(session).update(
            record.id, expected_version=expected_version, changes=columns
        )
    except Conflict as error:
        raise await _conflict(session, error, record.id) from error
    if units_changed:
        await _replace_units(session, updated, new_sites, new_groups)
    await _within_scope(session, subject, MANAGE, updated.id)
    after = _snapshot(updated, new_sites, new_groups)
    changes = [
        Change(name, before[name], value) for name, value in after.items() if before[name] != value
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
    await record_event(
        session,
        AnnouncementUpdated(
            announcement_id=updated.id,
            status=updated.status,
            changed_fields=[c.field for c in changes],
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    return await _view(session, subject, updated)


async def transition(  # noqa: PLR0913 - the action and its context, explicit
    session: AsyncSession,
    subject: Subject,
    announcement_id: uuid.UUID,
    action: AnnouncementAction,
    *,
    expected_version: int,
    reason: str | None,
    source: Source,
) -> AnnouncementView:
    """Publish, unpublish, archive or reopen. Only allowed moves; publish checks its rules."""
    permission = PUBLISH if action == AnnouncementAction.PUBLISH else MANAGE
    record = await _staff_record(session, subject, permission, announcement_id)
    if reason is not None and (action not in REASON_ACTIONS or len(reason) > REASON_MAX):
        code = "not_allowed" if action not in REASON_ACTIONS else "value_too_long"
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.reason",
                    code=code,
                    message_key=f"errors.field.{code}",
                    params={"max_length": REASON_MAX} if code == "value_too_long" else {},
                )
            ]
        )
    # Kept before the update: the repository updates this same (identity-mapped) object.
    previous = record.status
    try:
        target = MACHINE.apply(previous, action)
    except InvalidTransition as error:
        raise Conflict(
            code="invalid_transition", params={"from": previous, "action": action}
        ) from error
    extra: dict[str, Any] = {}
    if action == AnnouncementAction.PUBLISH:
        require(authorize(subject, PUBLISH, ANNOUNCEMENTS, await _facts(session, record)), PUBLISH)
        sites, groups = await _units(session, record.id)
        problems = publish_problems(
            title=record.title,
            body=record.body,
            audience=record.audience,
            units=len(sites) + len(groups),
            window=Window(record.publish_from, record.publish_until),
            now=_now(),
        )
        if problems:
            raise Conflict(code="cannot_publish", params={"reason": problems[0]})
        extra = {"published_at": _now(), "published_by": subject.user_id}
    try:
        updated = await AnnouncementRepository(session).update(
            record.id, expected_version=expected_version, changes={"status": target, **extra}
        )
    except Conflict as error:
        raise await _conflict(session, error, record.id) from error
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="status",
        changes=[Change("status", previous, target)],
        source=source,
        reason=(reason or "").strip() or None,
    )
    await record_event(
        session,
        AnnouncementStatusChanged(
            announcement_id=updated.id,
            action=action,
            from_status=previous,
            to_status=target,
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    return await _view(session, subject, updated)


async def remove(
    session: AsyncSession,
    subject: Subject,
    announcement_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Move to the trash (recoverable)."""
    record = await _staff_record(session, subject, MANAGE, announcement_id)
    try:
        deleted = await AnnouncementRepository(session).soft_delete(
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
        AnnouncementDeleted(announcement_id=record.id, status=record.status),
        aggregate_id=record.id,
        aggregate_version=deleted.version,
    )


async def restore(
    session: AsyncSession,
    subject: Subject,
    announcement_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> AnnouncementView:
    """Take out of the trash, exactly as it was."""
    record = await session.scalar(
        select(Announcement).where(
            Announcement.id == announcement_id, Announcement.deleted_at.is_not(None)
        )
    )
    if record is None or not subject.holds(MANAGE):
        raise NotFound(code="announcement_not_found")
    in_scope = await session.scalar(
        select(Announcement.id).where(
            Announcement.id == announcement_id, scope_filter(subject, MANAGE, ANNOUNCEMENTS)
        )
    )
    if in_scope is None:
        raise NotFound(code="announcement_not_found")
    if record.version != expected_version:
        raise await _conflict(
            session,
            Conflict(
                code="version_conflict",
                params={"expected_version": expected_version, "current_version": record.version},
            ),
            record.id,
        )
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
    await record_event(
        session,
        AnnouncementRestored(announcement_id=record.id, status=record.status),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    return await _view(session, subject, record)


# --- settings -------------------------------------------------------------------------------------

SETTINGS_RECORD_TYPE = "announcement_settings"


@dataclass(frozen=True)
class SettingsView:
    """The module's tenant settings."""

    require_second_publisher: bool
    version: int


async def get_settings(session: AsyncSession) -> SettingsView:
    """Current settings (defaults when never changed)."""
    row = await _settings(session)
    if row is None:
        return SettingsView(require_second_publisher=False, version=0)
    return SettingsView(row.require_second_publisher, row.version)


async def update_settings(
    session: AsyncSession,
    subject: Subject,
    *,
    expected_version: int,
    require_second_publisher: bool,
    source: Source,
) -> SettingsView:
    """Turn the four-eyes rule on or off (version 0 = never set)."""
    row = await _settings(session)
    current = 0 if row is None else row.version
    if current != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": current},
        )
    before = False if row is None else row.require_second_publisher
    if row is None:
        row = AnnouncementSettings(
            tenant_id=subject.tenant_id,
            require_second_publisher=require_second_publisher,
            version=1,
            updated_by=subject.user_id,
        )
        session.add(row)
    elif row.require_second_publisher == require_second_publisher:
        return SettingsView(row.require_second_publisher, row.version)
    else:
        row.require_second_publisher = require_second_publisher
        row.version += 1
        row.updated_at = _now()
        row.updated_by = subject.user_id
    await session.flush()
    # The four-eyes rule is a privileged setting: its changes keep who, when and from what.
    await record_changes(
        session,
        record_type=SETTINGS_RECORD_TYPE,
        record_id=subject.tenant_id,
        version=row.version,
        kind="updated",
        changes=[Change("require_second_publisher", before, require_second_publisher)],
        source=source,
    )
    await record_event(
        session,
        AnnouncementSettingsChanged(changed_fields=["require_second_publisher"]),
        aggregate_id=subject.tenant_id,
        aggregate_version=row.version,
    )
    return SettingsView(row.require_second_publisher, row.version)


__all__ = [
    "ANNOUNCEMENTS",
    "ANNOUNCEMENT_FIELDS",
    "ActionState",
    "AnnouncementView",
    "Feed",
    "PublicView",
    "SettingsView",
    "create",
    "feed",
    "get_announcement",
    "get_settings",
    "history",
    "list_announcements",
    "live_for",
    "remove",
    "restore",
    "staff_rows",
    "transition",
    "update",
    "update_settings",
]
