"""Incident templates: admin CRUD, copy, default, and the rules a create must follow (WP-020c).

REQ-INC-035. Templates are disabled, never deleted, so records created from them keep naming
them (AC2). One template per type is the default; the default cannot be disabled (the form must
always have one to start from). Starting values are checked when the template is saved, so a
template can never offer a value a create would refuse (REQ-WI-009 AC4); a value retired later
(a category disabled after the template was saved) is dropped by the form, which says so.
"""

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.modules.organization import existing_unit_ids
from app.modules.work_items.domain.classification import Impact, Urgency
from app.modules.work_items.domain.templates import (
    TEMPLATE_DESCRIPTION_MAX,
    TEMPLATE_GROUP_MAX,
    FieldRule,
    PickList,
    TemplateField,
    clean_impact_details,
    missing_required,
    rule_problems,
    rules_from_json,
    rules_to_json,
)
from app.modules.work_items.domain.types import (
    DESCRIPTION_MAX,
    WorkItemType,
    channel_problems,
    clean_subject,
    clean_tags,
)
from app.modules.work_items.events import WorkItemSettingsChanged
from app.modules.work_items.infra.models import WorkItemCategory, WorkItemTemplate
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service.settings import labels_of
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, ChangeKind, Source, record_changes
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
    return value.isoformat() if isinstance(value, datetime) else value


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


# --- writes ---------------------------------------------------------------------------------------


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
    defaults, codes = await _clean_defaults(session, wtype, raw_defaults)
    problems += codes
    problems += rule_problems(rules, defaults)
    if await _name_taken(session, wtype, labels, exclude=None):
        problems.append(("labels", "duplicate_name"))
    if problems:
        raise _problems(problems)
    template = WorkItemTemplate(
        type=wtype.code,
        labels=labels,
        description=description,
        group_name=group_name,
        is_default=False,
        for_requesters=bool(
            values.get("for_requesters", copied_from.for_requesters if copied_from else False)
        ),
        field_rules=rules_to_json(rules),
        defaults=defaults,
        copied_from_id=copied_from.id if copied_from else None,
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


async def update_template(  # noqa: PLR0913, C901, PLR0912 - one rule per setting, flat
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
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": template.version},
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
    rules = rules_from_json(template.field_rules)
    defaults: dict[str, Any] = dict(template.defaults)
    if "fields" in values:
        rules = _rules(values["fields"], rules)
        changes["field_rules"] = rules_to_json(rules)
    if "defaults" in values:
        defaults, codes = await _clean_defaults(session, wtype, values["defaults"] or {})
        problems += codes
        changes["defaults"] = defaults
    if "fields" in values or "defaults" in values:
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
    session: AsyncSession, wtype: WorkItemType, template_id: uuid.UUID | None
) -> WorkItemTemplate:
    """The template a new record uses: the one asked for, else the default (AC1, AC2)."""
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
    return found


def required_problems(
    template: WorkItemTemplate, values: Mapping[str, Any]
) -> list[tuple[str, str]]:
    """Fields the template requires that the create left empty."""
    return missing_required(rules_from_json(template.field_rules), values)
