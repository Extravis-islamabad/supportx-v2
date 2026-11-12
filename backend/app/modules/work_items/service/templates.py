"""Incident templates: admin CRUD, copy, default, and the rules a create must follow (WP-020c).

REQ-INC-035. Templates are disabled, never deleted, so records created from them keep naming
them (AC2). One template per type is the default; the default cannot be disabled (the form must
always have one to start from). Starting values are checked when the template is saved, so a
template can never offer a value a create would refuse (REQ-WI-009 AC4); a value retired later
(a category disabled after the template was saved) is dropped by the form, which says so.
"""

import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import FieldError, NotFound, ValidationFailed
from app.modules import metadata
from app.modules.identity_access import Subject
from app.modules.organization import (
    default_desk_id,
    existing_departments,
    existing_unit_ids,
    memberships,
)
from app.modules.work_items.domain.checklists import clean_items, item_problems
from app.modules.work_items.domain.classification import Impact, Urgency
from app.modules.work_items.domain.stages import (
    DEFAULT_PATH,
    parse_stage_rules,
    stage_rules_to_json,
)
from app.modules.work_items.domain.tasks import specs_of
from app.modules.work_items.domain.templates import (
    CUSTOM_PREFIX,
    FIXED_FIELDS,
    TEMPLATE_DESCRIPTION_MAX,
    TEMPLATE_GROUP_MAX,
    TEMPLATE_GROUPS_MAX,
    FieldRule,
    PickList,
    TemplateField,
    clean_impact_details,
    is_custom,
    missing_required,
    rule_problems,
    rules_from_json,
    rules_to_json,
)
from app.modules.work_items.domain.types import (
    DESCRIPTION_MAX,
    STANDARD_LIFECYCLE,
    WorkItemType,
    channel_problems,
    clean_subject,
    clean_tags,
)
from app.modules.work_items.events import WorkItemSettingsChanged
from app.modules.work_items.infra.models import WorkItemCategory, WorkItemTemplate
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import stages as stage_service
from app.modules.work_items.service.access import FIELDS
from app.modules.work_items.service.settings import labels_of
from app.shared.api.filters import compile_filter
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, ChangeKind, Source, record_changes, stale_version
from app.shared.richtext import is_blank, sanitize_html

TEMPLATE_RECORD_TYPE = "work_item_template"


class TemplateRepository(Repository[WorkItemTemplate]):
    """Templates of the session's tenant."""

    model = WorkItemTemplate


def _problems(problems: list[tuple[str, str]]) -> ValidationFailed:
    return ValidationFailed(
        errors=[
            FieldError(field=f"body.{f}", code=c, message_key=f"errors.field.{c}")
            for f, c in problems
        ]
    )


async def _limited_groups(
    session: AsyncSession, given: Iterable[Any], *, for_requesters: bool
) -> tuple[list[uuid.UUID], list[tuple[str, str]]]:
    """The groups a template is limited to (REQ-PRB-021), checked.

    Live groups of this tenant, at most 50; none for a template offered to requesters, which is
    for everyone (so the portal and the catalog never see a limited one).
    """
    ids = list(dict.fromkeys(uuid.UUID(str(g)) for g in given))
    if not ids:
        return [], []
    problems: list[tuple[str, str]] = []
    if len(ids) > TEMPLATE_GROUPS_MAX:
        problems.append(("limited_group_ids", "too_many_values"))
    if for_requesters:
        problems.append(("limited_group_ids", "limited_template_for_requesters"))
    live = await existing_unit_ids(session, "group", ids)
    if any(g not in live for g in ids):
        problems.append(("limited_group_ids", "group_not_found"))
    return ids, problems


async def offered_to(
    session: AsyncSession, subject: Subject, rows: Iterable[WorkItemTemplate]
) -> list[WorkItemTemplate]:
    """The templates `subject` is offered when creating (REQ-PRB-021 AC1).

    A limited one only to members of its groups; those who manage the settings see them all.
    """
    if subject.holds("settings.manage") or subject.holds("config.service_desk"):
        return list(rows)
    mine: frozenset[uuid.UUID] | None = None
    found: list[WorkItemTemplate] = []
    for row in rows:
        if row.limited_group_ids:
            mine = (
                mine
                if mine is not None
                else (await memberships(session, subject.user_id)).group_ids
            )
            if not mine.intersection(row.limited_group_ids):
                continue
        found.append(row)
    return found


async def list_templates(session: AsyncSession, wtype: WorkItemType) -> list[WorkItemTemplate]:
    """Every template of the type (disabled ones too, marked): default first, then by name."""
    await config.ensure_seeded(session, wtype)
    rows = list(
        await session.scalars(
            select(WorkItemTemplate).where(
                WorkItemTemplate.type == wtype.code, WorkItemTemplate.deleted_at.is_(None)
            )
        )
    )
    return sorted(
        rows,
        key=lambda t: (
            not t.is_default,
            (t.group_name or "").casefold(),
            ((t.labels or {}).get("en") or t.code or "").casefold(),
        ),
    )


async def _get(
    session: AsyncSession, wtype: WorkItemType, template_id: uuid.UUID
) -> WorkItemTemplate:
    found = await session.scalar(
        select(WorkItemTemplate).where(
            WorkItemTemplate.id == template_id,
            WorkItemTemplate.type == wtype.code,
            WorkItemTemplate.deleted_at.is_(None),
        )
    )
    if found is None:
        raise NotFound(code="template_not_found")
    return found


# --- checking what an admin saves -----------------------------------------------------------------


def _rules(raw: Mapping[str, Any] | None, base: Mapping[str, FieldRule]) -> dict[str, FieldRule]:
    """Sent rules merged over `base` (a partial update changes only the fields it names)."""
    merged = dict(base)
    for name, value in (raw or {}).items():
        if not isinstance(value, Mapping):
            raise _problems([(f"fields.{name}", "invalid_choice")])
        old = merged.get(name, FieldRule())
        merged[name] = FieldRule(
            shown=bool(value.get("shown", old.shown)),
            required=bool(value.get("required", old.required)),
            requester_can_see=bool(value.get("requester_can_see", old.requester_can_see)),
            requester_can_fill=bool(value.get("requester_can_fill", old.requester_can_fill)),
        )
    return merged


async def _clean_defaults(  # noqa: C901, PLR0912, PLR0915 - one rule per field, flat
    session: AsyncSession, wtype: WorkItemType, raw: Mapping[str, Any]
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Starting values a create would accept, plus (path, code) problems."""
    cleaned: dict[str, Any] = {}
    problems: list[tuple[str, str]] = []
    cat = await config.load(session, wtype)
    for name, value in raw.items():
        path = f"defaults.{name}"
        if value is None or value in ("", []):
            continue  # no starting value
        if name == TemplateField.SUBJECT:
            text, codes = clean_subject(str(value))
            problems += [(path, c) for c in codes]
            cleaned[name] = text
        elif name == TemplateField.DESCRIPTION:
            html = sanitize_html(str(value))
            if len(html) > DESCRIPTION_MAX:
                problems.append((path, "value_too_long"))
            if not is_blank(html):
                cleaned[name] = html
        elif name == TemplateField.IMPACT_DETAILS:
            details, codes = clean_impact_details(str(value))
            problems += [(path, c) for c in codes]
            cleaned[name] = details
        elif name == TemplateField.CHANNEL:
            problems += [(path, c) for c in channel_problems(str(value))]
            cleaned[name] = str(value)
        elif name in (TemplateField.IMPACT, TemplateField.URGENCY):
            allowed = set(Impact) if name == TemplateField.IMPACT else set(Urgency)
            if value not in allowed:
                problems.append((path, "invalid_choice"))
            cleaned[name] = str(value)
        elif name == TemplateField.LEVEL:
            if value not in cat.reason_codes(PickList.LEVEL):
                problems.append((path, "invalid_choice"))
            cleaned[name] = str(value)
        elif name == TemplateField.TAGS:
            tags, codes = clean_tags([str(v) for v in value] if isinstance(value, list) else [])
            problems += [(path, c) for c in codes]
            cleaned[name] = tags
        elif name in (TemplateField.SITE_ID, TemplateField.GROUP_ID):
            kind: Literal["site", "group"] = "site" if name == TemplateField.SITE_ID else "group"
            try:
                unit = uuid.UUID(str(value))
            except ValueError:
                problems.append((path, f"{kind}_not_found"))
                continue
            if unit not in await existing_unit_ids(session, kind, [unit]):
                problems.append((path, f"{kind}_not_found"))
            cleaned[name] = str(unit)
        elif name == TemplateField.DEPARTMENT_ID:
            try:
                department = uuid.UUID(str(value))
            except ValueError:
                problems.append((path, "department_not_found"))
                continue
            if department not in await existing_departments(session, [department]):
                problems.append((path, "department_not_found"))
            cleaned[name] = str(department)
        elif name == TemplateField.CATEGORY_ID:
            try:
                node_id = uuid.UUID(str(value))
            except ValueError:
                problems.append((path, "category_not_found"))
                continue
            node = await session.scalar(
                select(WorkItemCategory).where(
                    WorkItemCategory.id == node_id,
                    WorkItemCategory.type == wtype.code,
                    WorkItemCategory.deleted_at.is_(None),
                )
            )
            if node is None:
                problems.append((path, "category_not_found"))
            elif node.disabled_at is not None:
                problems.append((path, "category_disabled"))
            cleaned[name] = str(node_id)
        elif is_custom(name):
            # A custom field's starting value, checked by its own rules (WP-026).
            key = name.removeprefix(CUSTOM_PREFIX)
            value_by_key, found = await metadata.clean(
                session, wtype.code.value, {key: value}, creating=False
            )
            problems += [(path, code) for _, code in found]
            if not found and value_by_key.get(key) is not None:
                cleaned[name] = value_by_key[key]
        else:
            problems.append((path, "no_default_allowed"))
    return cleaned, problems


def _text(value: Any, field: str, limit: int) -> tuple[str | None, list[tuple[str, str]]]:  # noqa: ANN401 - JSON value
    text = " ".join(str(value or "").split()) or None
    if text is not None and len(text) > limit:
        return text, [(field, "value_too_long")]
    return text, []


async def _name_taken(
    session: AsyncSession,
    wtype: WorkItemType,
    labels: Mapping[str, str] | None,
    exclude: uuid.UUID | None,
) -> bool:
    english = (labels or {}).get("en", "").casefold()
    if not english:
        return False
    for other in await list_templates(session, wtype):
        if other.id != exclude and ((other.labels or {}).get("en") or "").casefold() == english:
            return True
    return False


def _json(value: Any) -> Any:  # noqa: ANN401 - JSON values
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list):  # the limited groups (REQ-PRB-021)
        return [_json(v) for v in value]
    return value


async def _changed(  # noqa: PLR0913 - the record, its changes and their context
    session: AsyncSession,
    wtype: WorkItemType,
    template: WorkItemTemplate,
    changes: list[Change],
    *,
    kind: ChangeKind,
    source: Source,
) -> None:
    await record_changes(
        session,
        record_type=TEMPLATE_RECORD_TYPE,
        record_id=template.id,
        version=template.version,
        kind=kind,
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        WorkItemSettingsChanged(type=wtype.code, changed_fields=["templates"]),
        aggregate_id=template.id,
        aggregate_version=template.version,
    )


async def _known_custom(
    session: AsyncSession,
    wtype: WorkItemType,
    rules: Mapping[str, FieldRule],
    defaults: Mapping[str, Any],
    sent: Iterable[str],
) -> tuple[dict[str, FieldRule], dict[str, Any], list[tuple[str, str]]]:
    """Rules and starting values without custom fields the tenant no longer has (WP-026).

    A rule sent now for an unknown field is refused; one left over from a field removed since
    is dropped quietly, so the template stays editable and copyable (REQ-INC-014 AC4).
    """
    names = {n for n in [*rules, *defaults] if is_custom(n)}
    if not names:
        return dict(rules), dict(defaults), []
    known = await metadata.definitions(session, wtype.code.value)
    stale = {n for n in names if n.removeprefix(CUSTOM_PREFIX) not in known}
    problems = [(f"fields.{n}", "unknown_field") for n in sorted(stale & set(sent))]
    return (
        {n: r for n, r in rules.items() if n not in stale},
        {n: v for n, v in defaults.items() if n not in stale},
        problems,
    )


# --- stage settings (staged types; ADR-041, REQ-REL-011, -013) -----------------------------------


async def _stage_settings(
    session: AsyncSession,
    wtype: WorkItemType,
    values: Mapping[str, Any],
    current: WorkItemTemplate | None,
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """The template's path and stage rules from `values`, checked (columns, problems).

    Unknown stages, fields or paths are refused, so a bad template is never saved; types
    without stages may set neither.
    """
    sent = [k for k in ("stage_path", "stage_rules") if k in values]
    if not sent:
        return {}, []
    if wtype.stages is None:
        return {}, [(k, "not_allowed") for k in sent]
    model = await stage_service.load_model(session, wtype)
    columns: dict[str, Any] = {}
    problems: list[tuple[str, str]] = []
    if "stage_path" in values:
        path = values["stage_path"]
        paths = await stage_service.enabled_paths(session, wtype)
        if path is None:
            problems.append(("stage_path", "required"))
        elif path not in paths and (current is None or current.stage_path != path):
            problems.append(("stage_path", "invalid_choice"))
        columns["stage_path"] = path
    if "stage_rules" in values:
        known = await metadata.definitions(session, wtype.code.value)
        fields = (
            {f.value for f in TemplateField}
            | set(wtype.own_fields)
            | {f"{CUSTOM_PREFIX}{k}" for k in known}
            # A plan section may be required to leave a stage (REQ-CHG-013, WP-045a D7).
            | {f"{PLAN_PREFIX}{section}" for section in wtype.plan_sections}
        )
        rules, codes = parse_stage_rules(
            values["stage_rules"] or {}, stages=[s.code for s in model.stages], fields=fields
        )
        problems += codes
        columns["stage_rules"] = stage_rules_to_json(rules) or None
    return columns, problems


PLAN_PREFIX = "plan."  # a plan section as a stage rule's field, e.g. plan.backout

# --- writes ---------------------------------------------------------------------------------------


def _template_tasks(raw: Any) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:  # noqa: ANN401 - JSON
    """A template's tasks (REQ-INC-040): each checked by place, its condition a list filter."""
    if raw in (None, []):
        return [], []
    found = specs_of(raw)
    problems = [p for p in found if isinstance(p, tuple)]
    if problems:
        return [], problems
    tasks = [{k: v for k, v in vars(t).items() if v is not None} for t in found]
    for index, task in enumerate(tasks):
        if task.get("condition") is None:
            continue
        try:
            compile_filter(task["condition"], FIELDS, now=datetime.now(UTC))
        except ValidationFailed:
            problems.append((f"tasks.{index}.condition", "invalid_value"))
    return tasks, problems


MAX_TEMPLATE_CHECKLISTS = 10


def _template_checklists(raw: Any) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:  # noqa: ANN401 - JSON
    """A template's checklists (REQ-INC-040): a title, items, an optional list-filter condition."""
    if raw in (None, []):
        return [], []
    if not isinstance(raw, list) or len(raw) > MAX_TEMPLATE_CHECKLISTS:
        return [], [("checklists", "too_many_items")]
    found: list[dict[str, Any]] = []
    problems: list[tuple[str, str]] = []
    for index, spec in enumerate(raw):
        spec = spec if isinstance(spec, dict) else {}  # noqa: PLW2901 - the same entry, typed
        title = " ".join(str(spec.get("title") or "").split())
        cleaned = clean_items(spec.get("items") or [])
        if not title:
            problems.append((f"checklists.{index}.title", "required"))
        problems += [(f"checklists.{index}.{f}", c) for f, c in item_problems(cleaned.items, 1000)]
        condition = spec.get("condition")
        if condition is not None:
            try:
                compile_filter(condition, FIELDS, now=datetime.now(UTC))
            except ValidationFailed:
                problems.append((f"checklists.{index}.condition", "invalid_value"))
        found.append(
            {"title": title, "items": cleaned.items}
            | ({"condition": condition} if condition is not None else {})
        )
    return found, problems


async def _lifecycle(
    session: AsyncSession, wtype: WorkItemType, value: object
) -> tuple[str | None, list[tuple[str, str]]]:
    """A template's transition set: one of the type's (NULL stored for the standard one)."""
    if value is None or value == STANDARD_LIFECYCLE:
        return None, []
    cat = await config.load(session, wtype)
    if not isinstance(value, str) or value not in cat.lifecycles:
        return None, [("lifecycle", "invalid_choice")]
    return value, []


async def create_template(
    session: AsyncSession,
    wtype: WorkItemType,
    values: Mapping[str, Any],
    *,
    source: Source,
    copied_from: WorkItemTemplate | None = None,
) -> WorkItemTemplate:
    """A new template (or a copy, marked as one: AC3). Never the default when created."""
    await config.ensure_seeded(session, wtype)
    labels = labels_of(values.get("labels"), allow_none=False)
    problems: list[tuple[str, str]] = []
    description, codes = _text(values.get("description"), "description", TEMPLATE_DESCRIPTION_MAX)
    problems += codes
    group_name, codes = _text(values.get("group_name"), "group_name", TEMPLATE_GROUP_MAX)
    problems += codes
    base = rules_from_json(copied_from.field_rules if copied_from else None)
    rules = _rules(values.get("fields"), base)
    raw_defaults = dict(copied_from.defaults) if copied_from else {}
    raw_defaults.update(values.get("defaults") or {})
    rules, raw_defaults, codes = await _known_custom(
        session, wtype, rules, raw_defaults, sent=(values.get("fields") or {})
    )
    problems += codes
    defaults, codes = await _clean_defaults(session, wtype, raw_defaults)
    problems += codes
    problems += rule_problems(rules, defaults)
    lifecycle, codes = await _lifecycle(
        session, wtype, values.get("lifecycle", copied_from.lifecycle if copied_from else None)
    )
    problems += codes
    tasks, codes = _template_tasks(values.get("tasks", copied_from.tasks if copied_from else None))
    problems += codes
    checklists, codes = _template_checklists(
        values.get("checklists", copied_from.checklists if copied_from else None)
    )
    problems += codes
    if await _name_taken(session, wtype, labels, exclude=None):
        problems.append(("labels", "duplicate_name"))
    stage_columns, codes = await _stage_settings(session, wtype, values, None)
    problems += codes
    for_requesters = bool(
        values.get("for_requesters", copied_from.for_requesters if copied_from else False)
    )
    limited, codes = await _limited_groups(
        session,
        values.get("limited_group_ids", copied_from.limited_group_ids if copied_from else []),
        for_requesters=for_requesters,
    )
    problems += codes
    if problems:
        raise _problems(problems)
    if wtype.stages is not None:  # a copy keeps the path and rules unless new ones are sent
        stage_columns.setdefault(
            "stage_path", copied_from.stage_path if copied_from else DEFAULT_PATH
        )
        stage_columns.setdefault("stage_rules", copied_from.stage_rules if copied_from else None)
    template = WorkItemTemplate(
        **stage_columns,
        type=wtype.code,
        desk_id=copied_from.desk_id if copied_from else await default_desk_id(session),
        labels=labels,
        description=description,
        group_name=group_name,
        is_default=False,
        for_requesters=for_requesters,
        limited_group_ids=limited,
        field_rules=rules_to_json(rules),
        defaults=defaults,
        copied_from_id=copied_from.id if copied_from else None,
        lifecycle=lifecycle,
        tasks=tasks,
        checklists=checklists,
    )
    await TemplateRepository(session).add(template)
    await _changed(
        session,
        wtype,
        template,
        [Change("labels", None, labels)]
        + ([Change("copied_from_id", None, str(copied_from.id))] if copied_from else []),
        kind="created",
        source=source,
    )
    return template


async def copy_template(
    session: AsyncSession,
    wtype: WorkItemType,
    template_id: uuid.UUID,
    *,
    labels: Mapping[str, Any],
    source: Source,
) -> WorkItemTemplate:
    """An independent copy under a new name (REQ-INC-035 AC3)."""
    original = await _get(session, wtype, template_id)
    return await create_template(
        session,
        wtype,
        {
            "labels": labels,
            "description": original.description,
            "group_name": original.group_name,
        },
        source=source,
        copied_from=original,
    )


async def _demote_default(session: AsyncSession, wtype: WorkItemType, source: Source) -> None:
    """The current default stops being one, with its own history entry (§7.4)."""
    previous = await session.scalars(
        select(WorkItemTemplate).where(
            WorkItemTemplate.type == wtype.code,
            WorkItemTemplate.is_default.is_(True),
            WorkItemTemplate.deleted_at.is_(None),
        )
    )
    for other in list(previous):
        demoted = await TemplateRepository(session).update(
            other.id, expected_version=other.version, changes={"is_default": False}
        )
        await _changed(
            session,
            wtype,
            demoted,
            [Change(field="is_default", old=True, new=False)],
            kind="updated",
            source=source,
        )


async def update_template(  # noqa: PLR0913, C901, PLR0912, PLR0915 - one rule per setting, flat
    session: AsyncSession,
    wtype: WorkItemType,
    template_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
) -> WorkItemTemplate:
    """Change any part of a template; making it the default unsets the previous default."""
    template = await _get(session, wtype, template_id)
    if template.version != expected_version:
        raise await stale_version(
            session,
            template,
            expected_version=expected_version,
            record_type=TEMPLATE_RECORD_TYPE,
            record_id=template.id,
        )
    problems: list[tuple[str, str]] = []
    changes: dict[str, Any] = {}
    if "labels" in values:
        changes["labels"] = labels_of(values["labels"], allow_none=template.code is not None)
        if await _name_taken(session, wtype, changes["labels"], exclude=template.id):
            problems.append(("labels", "duplicate_name"))
    if "description" in values:
        changes["description"], codes = _text(
            values["description"], "description", TEMPLATE_DESCRIPTION_MAX
        )
        problems += codes
    if "group_name" in values:
        changes["group_name"], codes = _text(values["group_name"], "group_name", TEMPLATE_GROUP_MAX)
        problems += codes
    if "for_requesters" in values:
        changes["for_requesters"] = bool(values["for_requesters"])
    if "limited_group_ids" in values or "for_requesters" in values:
        changes["limited_group_ids"], codes = await _limited_groups(
            session,
            values.get("limited_group_ids", template.limited_group_ids) or [],
            for_requesters=changes.get("for_requesters", template.for_requesters),
        )
        problems += codes
    if "tasks" in values:  # REQ-INC-040: new records only; existing records keep their tasks
        changes["tasks"], codes = _template_tasks(values["tasks"])
        problems += codes
    if "checklists" in values:  # REQ-INC-040: new records only; existing records keep theirs
        changes["checklists"], codes = _template_checklists(values["checklists"])
        problems += codes
    if "lifecycle" in values:  # new records only: running ones keep theirs (REQ-INC-049 style)
        changes["lifecycle"], codes = await _lifecycle(session, wtype, values["lifecycle"])
        problems += codes
    stage_columns, codes = await _stage_settings(session, wtype, values, template)
    changes.update(stage_columns)
    problems += codes
    rules = rules_from_json(template.field_rules)
    defaults: dict[str, Any] = dict(template.defaults)
    if "fields" in values:
        rules = _rules(values["fields"], rules)
    if "defaults" in values:
        defaults = dict(values["defaults"] or {})
    if "fields" in values or "defaults" in values:
        rules, defaults, codes = await _known_custom(
            session, wtype, rules, defaults, sent=(values.get("fields") or {})
        )
        problems += codes
        changes["field_rules"] = rules_to_json(rules)
    if "defaults" in values:
        defaults, codes = await _clean_defaults(session, wtype, defaults)
        problems += codes
    if "fields" in values or "defaults" in values:
        changes["defaults"] = defaults
        problems += rule_problems(rules, defaults)
    disabled = values.get("disabled")
    make_default = values.get("is_default")
    if make_default is False and template.is_default:
        # There is always one default: choose another template as the default instead.
        problems.append(("is_default", "default_required"))
    if disabled is True and (template.is_default or make_default):
        problems.append(("disabled", "default_cannot_be_disabled"))
    if make_default and (template.disabled_at is not None and disabled is not False):
        problems.append(("is_default", "disabled_cannot_be_default"))
    if problems:
        raise _problems(problems)
    if disabled is not None and bool(disabled) != (template.disabled_at is not None):
        changes["disabled_at"] = datetime.now(UTC) if disabled else None
    if make_default and not template.is_default:
        await _demote_default(session, wtype, source)
        changes["is_default"] = True
    before = {k: getattr(template, k) for k in changes}
    changes = {k: v for k, v in changes.items() if before[k] != v}
    if not changes:
        return template
    updated = await TemplateRepository(session).update(
        template.id, expected_version=expected_version, changes=changes
    )
    await _changed(
        session,
        wtype,
        updated,
        [
            Change(
                "disabled" if k == "disabled_at" else k,
                _json(before[k]) if k != "disabled_at" else before[k] is not None,
                _json(v) if k != "disabled_at" else v is not None,
            )
            for k, v in changes.items()
        ],
        kind="updated",
        source=source,
    )
    return updated


# --- creating a record from a template ------------------------------------------------------------


async def for_create(
    session: AsyncSession,
    wtype: WorkItemType,
    template_id: uuid.UUID | None,
    subject: Subject | None = None,
) -> WorkItemTemplate:
    """The template a new record uses: the one asked for, else the default (AC1, AC2).

    With `subject`, a template limited to groups they are not in is refused as not offered
    (REQ-PRB-021 AC1): the API never lets past what the form does not offer.
    """
    await config.ensure_seeded(session, wtype)
    if template_id is None:
        found = await session.scalar(
            select(WorkItemTemplate).where(
                WorkItemTemplate.type == wtype.code,
                WorkItemTemplate.is_default.is_(True),
                WorkItemTemplate.deleted_at.is_(None),
            )
        )
        if found is None:  # pragma: no cover - seeding always makes one and it cannot go
            msg = "no default template"
            raise RuntimeError(msg)
        return found
    try:
        found = await _get(session, wtype, template_id)
    except NotFound as error:
        raise _problems([("template_id", "template_not_found")]) from error
    if found.disabled_at is not None:
        raise _problems([("template_id", "template_disabled")])
    if (
        subject is not None
        and found.limited_group_ids
        and not await offered_to(session, subject, [found])
    ):
        raise _problems([("template_id", "template_not_offered")])
    return found


async def required_problems(
    session: AsyncSession,
    wtype: WorkItemType,
    template: WorkItemTemplate,
    values: Mapping[str, Any],
) -> list[tuple[str, str]]:
    """Fields the template requires that the create left empty.

    Custom fields retired or removed since the template was saved take no new values, so their
    rules no longer apply (WP-026).
    """
    rules = rules_from_json(template.field_rules)
    custom = [n for n in rules if is_custom(n)]
    if custom:
        known = await metadata.definitions(session, wtype.code.value)
        for name in custom:
            found = known.get(name.removeprefix(CUSTOM_PREFIX))
            if found is None or found.retired:
                del rules[name]
    return missing_required(rules, values)


async def emptied_required(
    session: AsyncSession,
    template_id: uuid.UUID | None,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> list[tuple[str, str]]:
    """Fields the record's template requires that this change would empty (D-086).

    Only emptying is refused: a field made required after the record was created blocks
    nothing until someone tries to clear it. A turned-off template still counts (the record was
    created with its rules).
    """
    if template_id is None:
        return []
    template = await session.scalar(
        select(WorkItemTemplate).where(WorkItemTemplate.id == template_id)
    )
    if template is None:
        return []
    rules = rules_from_json(template.field_rules)
    return [
        (name, "required")
        for name, value in after.items()
        if name in rules
        and rules[name].required
        and not (name in set(TemplateField) and TemplateField(name) in FIXED_FIELDS)
        and _empty(value)
        and not _empty(before.get(name))
    ]


def _empty(value: Any) -> bool:  # noqa: ANN401 - any field value
    return value is None or value in ("", [])
