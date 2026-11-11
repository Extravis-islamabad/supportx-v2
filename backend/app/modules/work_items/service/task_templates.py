"""Task templates (WP-046a S1; REQ-INC-074) and a record template's tasks (REQ-INC-040).

An admin keeps task templates per work item type: one task or an ordered set of up to 20. A
technician adds a template's tasks to a record they may work on, each ready to edit (AC1); a
disabled template is not offered and cannot be added (AC2).

A record template may carry tasks too, each with an optional condition (a filter DSL tree over
the record's list fields). When a record is made from it, the tasks whose condition the new
record matches are added, and the record's history says the template added them (REQ-INC-040).
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import FieldError, NotFound, ValidationFailed
from app.modules.identity_access import Subject
from app.modules.work_items.domain.tasks import TaskSpec, specs_of
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import WorkItem, WorkItemTaskTemplate
from app.modules.work_items.service import parts
from app.modules.work_items.service.access import FIELDS
from app.shared.api.filters import compile_filter
from app.shared.db.repository import Repository
from app.shared.history import Source

NAME_MAX, DESCRIPTION_MAX = 200, 2000


class TaskTemplateRepository(Repository[WorkItemTaskTemplate]):
    """Task templates of the session's tenant."""

    model = WorkItemTaskTemplate


def _problems(problems: Sequence[tuple[str, str]]) -> ValidationFailed:
    return ValidationFailed(
        errors=[FieldError(field=f, code=c, message_key=f"errors.field.{c}") for f, c in problems]
    )


def _specs(raw: Any) -> list[dict[str, Any]]:  # noqa: ANN401 - JSON from the request
    """The template's tasks, checked, as stored (JSON); 422 naming each one's place."""
    found = specs_of(raw)
    if found and isinstance(found[0], tuple):
        raise _problems([p for p in found if isinstance(p, tuple)])
    return [
        {k: v for k, v in vars(spec).items() if v is not None}
        for spec in found
        if isinstance(spec, TaskSpec)
    ]


def _name(values: dict[str, Any], problems: list[tuple[str, str]]) -> str | None:
    name = values.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append(("name", "required"))
        return None
    if len(name.strip()) > NAME_MAX:
        problems.append(("name", "value_too_long"))
    return name.strip()


async def list_templates(
    session: AsyncSession, wtype: WorkItemType, *, include_disabled: bool
) -> list[WorkItemTaskTemplate]:
    """The type's task templates by name; disabled ones only for the admin's screen (AC2)."""
    query = select(WorkItemTaskTemplate).where(
        WorkItemTaskTemplate.type == wtype.code, WorkItemTaskTemplate.deleted_at.is_(None)
    )
    if not include_disabled:
        query = query.where(WorkItemTaskTemplate.disabled_at.is_(None))
    return list(await session.scalars(query.order_by(WorkItemTaskTemplate.name)))


async def create_template(
    session: AsyncSession, wtype: WorkItemType, values: dict[str, Any]
) -> WorkItemTaskTemplate:
    """A new task template of the type: a name and one task or a set."""
    problems: list[tuple[str, str]] = []
    name = _name(values, problems)
    description = values.get("description")
    if description is not None and len(description) > DESCRIPTION_MAX:
        problems.append(("description", "value_too_long"))
    if problems:
        raise _problems(problems)
    assert name is not None  # noqa: S101 - checked above
    return await TaskTemplateRepository(session).add(
        WorkItemTaskTemplate(
            type=wtype.code,
            name=name,
            description=description,
            tasks=_specs(values.get("tasks")),
        )
    )


async def _template(
    session: AsyncSession, wtype: WorkItemType, template_id: uuid.UUID
) -> WorkItemTaskTemplate:
    found: WorkItemTaskTemplate | None = await session.scalar(
        select(WorkItemTaskTemplate).where(
            WorkItemTaskTemplate.id == template_id,
            WorkItemTaskTemplate.type == wtype.code,
            WorkItemTaskTemplate.deleted_at.is_(None),
        )
    )
    if found is None:
        raise NotFound(code="task_template_not_found")
    return found


async def update_template(
    session: AsyncSession,
    wtype: WorkItemType,
    template_id: uuid.UUID,
    values: dict[str, Any],
    *,
    expected_version: int,
) -> WorkItemTaskTemplate:
    """Change a task template (If-Match); `disabled` true stops offering it (AC2)."""
    row = await _template(session, wtype, template_id)
    problems: list[tuple[str, str]] = []
    changes: dict[str, Any] = {}
    if "name" in values:
        changes["name"] = _name(values, problems)
    if "description" in values:
        description = values["description"]
        if description is not None and len(description) > DESCRIPTION_MAX:
            problems.append(("description", "value_too_long"))
        changes["description"] = description
    if problems:
        raise _problems(problems)
    if "tasks" in values:
        changes["tasks"] = _specs(values["tasks"])
    if "disabled" in values:
        changes["disabled_at"] = (
            (row.disabled_at or datetime.now(UTC)) if values["disabled"] else None
        )
    return await TaskTemplateRepository(session).update(
        row.id, expected_version=expected_version, changes=changes
    )


async def add_from_template(  # noqa: PLR0913 - the record, the template and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    template_id: uuid.UUID,
    *,
    source: Source,
) -> list[Any]:
    """The template's tasks added at the end of the record's list, ready to edit (AC1)."""
    template = await _template(session, wtype, template_id)
    if template.disabled_at is not None:
        raise NotFound(code="task_template_not_found")  # not offered (AC2)
    return [
        await parts.create_task(
            session, subject, wtype, record_id, _task_values(spec), source=source
        )
        for spec in template.tasks
    ]


def _task_values(spec: dict[str, Any]) -> dict[str, Any]:
    """A stored spec as the values a new task takes (its condition is not a task field)."""
    return {k: v for k, v in spec.items() if k != "condition"}


def record_template_tasks(raw: Any) -> list[dict[str, Any]]:  # noqa: ANN401 - JSON from the request
    """A record template's tasks, checked (422 by place); conditions are checked on use."""
    if raw in (None, []):
        return []
    return _specs(raw)


def check_conditions(wtype: WorkItemType, tasks: Sequence[dict[str, Any]]) -> None:
    """Each condition is a valid filter over the type's list fields (422 by place)."""
    del wtype  # one field list for every type until type-own fields are shared (WP-045d S4c)
    fields = FIELDS  # the list's built-in fields (type-own fields join with WP-045d S4c)
    for index, spec in enumerate(tasks):
        if spec.get("condition") is not None:
            compile_filter(
                spec["condition"],
                fields,
                now=datetime.now(UTC),
                path=f"tasks.{index}.condition",
            )


async def add_template_tasks(  # noqa: PLR0913 - the new record, its template's tasks, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record: WorkItem,
    tasks: Sequence[dict[str, Any]],
    *,
    source: Source,
) -> int:
    """The template's tasks whose condition the new record matches (REQ-INC-040); how many."""
    del wtype  # one field list for every type until type-own fields are shared (WP-045d S4c)
    fields = FIELDS  # the list's built-in fields (type-own fields join with WP-045d S4c)
    added = 0
    for spec in tasks:
        condition = spec.get("condition")
        if condition is not None:
            matches = await session.scalar(
                select(WorkItem.id).where(
                    WorkItem.id == record.id,
                    compile_filter(condition, fields, now=datetime.now(UTC)),
                )
            )
            if matches is None:
                continue
        await parts.create_template_task(
            session, record, _task_values(spec), source=source, by=subject.user_id
        )
        added += 1
    return added


__all__ = [
    "add_from_template",
    "add_template_tasks",
    "check_conditions",
    "create_template",
    "list_templates",
    "record_template_tasks",
    "update_template",
]
