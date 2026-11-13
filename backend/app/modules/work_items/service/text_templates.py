"""Reply and resolution templates (WP-046a S5a; REQ-INC-041, REQ-INC-042).

A template is personal or shared (the coordinator, lane B reviews):
- **personal**: its owner's only. Nobody else reads, lists or changes it, administrators
  included; it is made by anyone who may view the type's records.
- **shared**: offered to everyone who may view the type's records, or only to the listed
  groups' members; written only with the type's settings right.

Its text comes in the languages the tenant writes (en, ar, ur). Filling it for a record takes
the requester's language first, then the tenant's default, then whatever the template has, and
puts the record's values in its variables (the type's one catalogue, the same names and labels
notifications use); an empty variable reads "not set" in that language (REQ-INC-041 AC1-AC3).
A resolution template names categories: for a record in one of them it is offered first
(REQ-INC-042 AC2).
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
from app.modules.identity_access import Subject, notifiable_people
from app.modules.organization import existing_unit_ids, offered_languages
from app.modules.work_items.domain.text_templates import (
    BODY_MAX,
    CATEGORIES_MAX,
    GROUPS_MAX,
    LANGUAGES,
    NAME_MAX,
    SUBJECT_MAX,
    TemplateKind,
    TemplateVisibility,
    fill,
    pick_language,
    unknown_variables,
)
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.events import WorkItemReplyTemplatesChanged
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemCategory,
    WorkItemReplyTemplate,
)
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.notifications import VARIABLES, record_values
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes
from app.shared.labels import label
from app.shared.notifications.ports import LabelRef, Localised, VariableValue
from app.shared.richtext import is_blank, sanitize_html

# The type's settings right: shared templates are written with it.
SETTINGS_RIGHTS = ("config.service_desk", "settings.manage")
NOT_FOUND = "reply_template_not_found"
# The field codes a template's checks give (labels: errors.field.*; checked in test_domain).
FIELD_PROBLEMS = frozenset(
    {
        "duplicate_name",
        "invalid_choice",
        "not_for_personal",
        "not_for_replies",
        "required",
        "too_many_values",
        "unknown_category",
        "unknown_group",
        "unknown_variable",
        "value_too_long",
    }
)
NOT_SET = "text_template.not_set"  # the placeholder of an empty variable, per language
OFFERED = frozenset(v.name for v in VARIABLES)


class _Repository(Repository[WorkItemReplyTemplate]):
    model = WorkItemReplyTemplate


@dataclass(frozen=True)
class TemplateInput:
    """What a template is, as the admin or its owner writes it."""

    kind: TemplateKind
    name: str
    subject: str | None
    bodies: Mapping[str, str]
    visibility: TemplateVisibility
    group_ids: Sequence[uuid.UUID] = ()
    category_ids: Sequence[uuid.UUID] = ()


@dataclass(frozen=True)
class Filled:
    """A template filled for one record, in one language."""

    language: str
    subject: str | None
    body: str


def may_manage_shared(subject: Subject) -> bool:
    """Whether `subject` may write shared templates (the type's settings right)."""
    return any(subject.holds(right) for right in SETTINGS_RIGHTS)


def _require_view(subject: Subject, wtype: WorkItemType) -> None:
    if not subject.holds(wtype.permission("view")):
        raise PermissionDenied(
            params={"permission": wtype.permission("view"), "reason": "no_permission"}
        )


def _readable(subject: Subject) -> Any:  # noqa: ANN401 - a SQL condition
    """Shared ones (all, or the subject's groups'), and the subject's own personal ones."""
    mine = (WorkItemReplyTemplate.visibility == TemplateVisibility.PERSONAL.value) & (
        WorkItemReplyTemplate.owner_id == subject.user_id
    )
    shared = (WorkItemReplyTemplate.visibility == TemplateVisibility.SHARED.value) & or_(
        func.cardinality(WorkItemReplyTemplate.group_ids) == 0,
        WorkItemReplyTemplate.group_ids.overlap(list(subject.group_ids)),
    )
    return mine | shared


async def offered(
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    kind: TemplateKind,
    *,
    category_id: uuid.UUID | None = None,
) -> list[WorkItemReplyTemplate]:
    """The templates `subject` may use, by name; a resolution's categories first (042 AC2)."""
    _require_view(subject, wtype)
    rows = list(
        await session.scalars(
            select(WorkItemReplyTemplate)
            .where(
                WorkItemReplyTemplate.type == wtype.code,
                WorkItemReplyTemplate.kind == kind.value,
                WorkItemReplyTemplate.deleted_at.is_(None),
                _readable(subject),
            )
            .order_by(func.lower(WorkItemReplyTemplate.name), WorkItemReplyTemplate.id)
        )
    )
    if category_id is None:
        return rows
    first = [r for r in rows if category_id in (r.category_ids or [])]
    return first + [r for r in rows if r not in first]


async def managed(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, kind: TemplateKind
) -> list[WorkItemReplyTemplate]:
    """The admin screen's list: the shared templates, and the subject's own personal ones.

    Another person's personal template is never listed, whoever asks (the coordinator). A
    shared one limited to groups is listed to those groups' members and to holders of the
    settings right only (lane B): the group limit keeps its text from everyone else too.
    """
    _require_view(subject, wtype)
    readable = (
        (WorkItemReplyTemplate.visibility == TemplateVisibility.PERSONAL.value)
        & (WorkItemReplyTemplate.owner_id == subject.user_id)
    ) | (WorkItemReplyTemplate.visibility == TemplateVisibility.SHARED.value)
    condition = readable if may_manage_shared(subject) else _readable(subject)
    rows = await session.scalars(
        select(WorkItemReplyTemplate)
        .where(
            WorkItemReplyTemplate.type == wtype.code,
            WorkItemReplyTemplate.kind == kind.value,
            WorkItemReplyTemplate.deleted_at.is_(None),
            condition,
        )
        .order_by(func.lower(WorkItemReplyTemplate.name), WorkItemReplyTemplate.id)
    )
    return list(rows)


async def _row(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, template_id: uuid.UUID
) -> WorkItemReplyTemplate:
    """A template the subject may read; another person's personal one does not exist for them."""
    found: WorkItemReplyTemplate | None = await session.scalar(
        select(WorkItemReplyTemplate).where(
            WorkItemReplyTemplate.id == template_id,
            WorkItemReplyTemplate.type == wtype.code,
            WorkItemReplyTemplate.deleted_at.is_(None),
            _readable(subject)
            | (
                (WorkItemReplyTemplate.visibility == TemplateVisibility.SHARED.value)
                & literal(may_manage_shared(subject))
            ),
        )
    )
    if found is None or (
        found.visibility == TemplateVisibility.PERSONAL.value and found.owner_id != subject.user_id
    ):
        raise NotFound(code=NOT_FOUND)
    return found


def _may_write(subject: Subject, visibility: TemplateVisibility) -> None:
    if visibility is TemplateVisibility.SHARED and not may_manage_shared(subject):
        raise PermissionDenied(params={"permission": SETTINGS_RIGHTS[0], "reason": "no_permission"})


async def _clean(  # noqa: C901, PLR0912 - one check per field, flat
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    given: TemplateInput,
    *,
    except_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    problems: list[tuple[str, str]] = []
    name = " ".join(given.name.split())
    if not name:
        problems.append(("name", "required"))
    elif len(name) > NAME_MAX:
        problems.append(("name", "value_too_long"))
    subject_line = " ".join((given.subject or "").split()) or None
    if subject_line is not None and len(subject_line) > SUBJECT_MAX:
        problems.append(("subject", "value_too_long"))
    if subject_line is not None and unknown_variables(subject_line, OFFERED):
        problems.append(("subject", "unknown_variable"))
    bodies: dict[str, str] = {}
    for language, text in given.bodies.items():
        if language not in LANGUAGES:
            problems.append((f"bodies.{language}", "invalid_choice"))
            continue
        clean = sanitize_html(text)
        if is_blank(clean):
            continue
        if len(clean) > BODY_MAX:
            problems.append((f"bodies.{language}", "value_too_long"))
        if unknown_variables(clean, OFFERED):
            problems.append((f"bodies.{language}", "unknown_variable"))
        bodies[language] = clean
    if not bodies:
        problems.append(("bodies", "required"))
    groups = list(dict.fromkeys(given.group_ids))
    categories = list(dict.fromkeys(given.category_ids))
    if len(groups) > GROUPS_MAX:
        problems.append(("group_ids", "too_many_values"))
    if len(categories) > CATEGORIES_MAX:
        problems.append(("category_ids", "too_many_values"))
    if given.visibility is TemplateVisibility.PERSONAL and groups:
        problems.append(("group_ids", "not_for_personal"))
    if given.kind is TemplateKind.REPLY and categories:
        problems.append(("category_ids", "not_for_replies"))
    # Ids from this tenant only (the session's RLS hides any other tenant's): an unknown one is
    # refused, never stored.
    if groups and set(groups) - await existing_unit_ids(session, "group", groups):
        problems.append(("group_ids", "unknown_group"))
    if categories:
        known = set(
            await session.scalars(
                select(WorkItemCategory.id).where(
                    WorkItemCategory.id.in_(categories),
                    WorkItemCategory.type == wtype.code,
                    WorkItemCategory.deleted_at.is_(None),
                )
            )
        )
        if set(categories) - known:
            problems.append(("category_ids", "unknown_category"))
    owner = subject.user_id if given.visibility is TemplateVisibility.PERSONAL else None
    if name and not any(p[0] == "name" for p in problems):
        same = select(WorkItemReplyTemplate.id).where(
            WorkItemReplyTemplate.type == wtype.code,
            WorkItemReplyTemplate.kind == given.kind.value,
            WorkItemReplyTemplate.deleted_at.is_(None),
            func.lower(WorkItemReplyTemplate.name) == name.lower(),
            WorkItemReplyTemplate.owner_id.is_(None)
            if owner is None
            else WorkItemReplyTemplate.owner_id == owner,
        )
        if except_id is not None:
            same = same.where(WorkItemReplyTemplate.id != except_id)
        if await session.scalar(same) is not None:
            problems.append(("name", "duplicate_name"))
    if problems:
        raise items.field_errors(problems)
    return {
        "kind": given.kind.value,
        "name": name,
        "subject": subject_line,
        "bodies": bodies,
        "body": None,
        "visibility": given.visibility.value,
        "owner_id": owner,
        "group_ids": groups,
        "category_ids": categories,
    }


async def _changed(
    session: AsyncSession,
    wtype: WorkItemType,
    row: WorkItemReplyTemplate,
    kind: str,
    source: Source,
) -> None:
    await record_changes(
        session,
        record_type="work_item_reply_template",
        record_id=row.id,
        version=row.version,
        kind="deleted" if kind == "deleted" else ("created" if kind == "created" else "updated"),
        changes=[] if kind == "deleted" else [Change("name", None, row.name)],
        source=source,
    )
    await record_event(
        session,
        WorkItemReplyTemplatesChanged(type=wtype.code, template_id=row.id),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def create(
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    given: TemplateInput,
    *,
    source: Source,
) -> WorkItemReplyTemplate:
    """A new template: personal (anyone who may view the type) or shared (the settings right)."""
    _require_view(subject, wtype)
    _may_write(subject, given.visibility)
    values = await _clean(session, subject, wtype, given)
    row = await _Repository(session).add(WorkItemReplyTemplate(type=wtype.code, **values))
    await _changed(session, wtype, row, "created", source)
    return row


async def update(  # noqa: PLR0913 - the template, its version and the change, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    template_id: uuid.UUID,
    given: TemplateInput,
    *,
    expected_version: int,
    source: Source,
) -> WorkItemReplyTemplate:
    """Change a template (If-Match): one's own personal one, or a shared one with the right.

    Sharing a personal template, or taking a shared one back, needs the settings right too.
    """
    row = await _row(session, subject, wtype, template_id)
    _may_write(subject, TemplateVisibility(row.visibility))
    _may_write(subject, given.visibility)
    values = await _clean(session, subject, wtype, given, except_id=row.id)
    updated = await _Repository(session).update(
        row.id, expected_version=expected_version, changes=values
    )
    await _changed(session, wtype, updated, "updated", source)
    return updated


async def delete(  # noqa: PLR0913 - the template, its version and the context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    template_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Remove a template (soft delete); text already used stays where it was put."""
    row = await _row(session, subject, wtype, template_id)
    _may_write(subject, TemplateVisibility(row.visibility))
    removed = await _Repository(session).soft_delete(row.id, expected_version=expected_version)
    await _changed(session, wtype, removed, "deleted", source)


def _localise(value: VariableValue, language: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, LabelRef):
        return label(value.key, language)
    if isinstance(value, Localised):
        own = value.texts.get(language) or value.texts.get("en")
        if own:
            return own
        return label(value.fallback, language) if value.fallback else None
    return str(value)


async def fill_for(  # noqa: PLR0913 - the template, the record and the reader, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    template_id: uuid.UUID,
    record_id: uuid.UUID,
    *,
    languages: Iterable[str | None] = (),
) -> Filled:
    """The template filled with the record's values (REQ-INC-041 AC1-AC3).

    The record must be one the subject may see, and the template one offered to them (a shared
    one limited to groups only for those groups' members). The language: the one the screen
    asks for, then the requester's own, then the tenant's default, then any the template has.
    """
    row = await _row(session, subject, wtype, template_id)
    if (
        row.visibility == TemplateVisibility.SHARED.value
        and row.group_ids
        and not set(row.group_ids) & set(subject.group_ids)
    ):
        raise NotFound(code=NOT_FOUND)
    record: WorkItem = await items.visible_record(session, subject, wtype, record_id)
    person = (await notifiable_people(session, [record.requester_id])).get(record.requester_id)
    languages = [*languages, person.language if person else None]
    cat = await config.load(session, wtype)
    bodies = dict(row.bodies or {})
    if not bodies and row.body:
        bodies = {"en": row.body}
    language = pick_language(bodies, [*languages, await _tenant_language(session)]) or "en"
    raw = await record_values(session, record, cat, subject.user_id)
    values = {name: _localise(value, language) for name, value in raw.items()}
    not_set = label(NOT_SET, language)
    return Filled(
        language=language,
        subject=fill(row.subject, values, not_set, html=False) if row.subject else None,
        # Sanitised again once filled (lane C): the values went in escaped, and the text meets
        # the editor's allow-list whatever was stored before the allow-list last changed.
        body=sanitize_html(fill(bodies.get(language, ""), values, not_set)),
    )


async def _tenant_language(session: AsyncSession) -> str:
    _offered, default = await offered_languages(session)
    return default


__all__ = [
    "FIELD_PROBLEMS",
    "NOT_FOUND",
    "SETTINGS_RIGHTS",
    "Filled",
    "TemplateInput",
    "create",
    "delete",
    "fill_for",
    "managed",
    "may_manage_shared",
    "offered",
    "update",
]
