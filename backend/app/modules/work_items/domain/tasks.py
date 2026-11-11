"""Task details, dependencies and templates (WP-046a S1; REQ-INC-040, 073..075). Pure rules.

- Details (REQ-INC-073): an end is never before its start (AC1); percent, estimate, cost and the
  reminder stay in range; a reminder needs a scheduled start to be before.
- Dependencies (REQ-INC-075): a task waits for tasks of the same record; a loop is refused (AC3);
  starting or completing a task whose predecessors are still open is refused, naming them (AC1),
  unless the type's setting makes it a warning.
- Templates (REQ-INC-074, -040): a task spec is what a template adds; a set holds 1-20 of them.
"""

from collections.abc import Collection, Hashable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.modules.work_items.domain.parts import DESCRIPTION_MAX, TITLE_MAX, TaskPriority, TaskStatus

MAX_ESTIMATE_MINUTES = 365 * 24 * 60
MAX_REMINDER_MINUTES = 7 * 24 * 60
MAX_COST = Decimal("9999999999.99")
MAX_TEMPLATE_TASKS = 20
MAX_DEPENDENCIES = 20  # predecessors of one task
TASK_TYPE_MAX = 40
# A move into one of these needs the predecessors done (REQ-INC-075 AC1).
GATED_STATUSES = frozenset({TaskStatus.IN_PROGRESS.value, TaskStatus.DONE.value})
FINISHED_STATUSES = frozenset({TaskStatus.DONE.value, TaskStatus.CANCELED.value})


class DependencyMode(StrEnum):
    """What an open predecessor does (REQ-INC-075): refuses the move, or only warns."""

    BLOCK = "block"
    WARN = "warn"


def detail_problems(values: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(field, code) for each detail that does not hold together, in the order checked."""
    problems: list[tuple[str, str]] = []
    for start, end in (("scheduled_start", "scheduled_end"), ("actual_start", "actual_end")):
        begins, ends = values.get(start), values.get(end)
        if isinstance(begins, datetime) and isinstance(ends, datetime) and ends < begins:
            problems.append((end, "end_before_start"))
    estimate = values.get("estimated_minutes")
    if estimate is not None and not 0 <= estimate <= MAX_ESTIMATE_MINUTES:
        problems.append(("estimated_minutes", "out_of_range"))
    percent = values.get("percent_complete")
    if percent is not None and not 0 <= percent <= 100:  # noqa: PLR2004 - a percentage
        problems.append(("percent_complete", "out_of_range"))
    cost = values.get("extra_cost")
    if cost is not None and not Decimal(0) <= Decimal(cost) <= MAX_COST:
        problems.append(("extra_cost", "out_of_range"))
    reminder = values.get("remind_before_minutes")
    if reminder is not None:
        if not 0 <= reminder <= MAX_REMINDER_MINUTES:
            problems.append(("remind_before_minutes", "out_of_range"))
        elif values.get("scheduled_start") is None:
            problems.append(("remind_before_minutes", "needs_scheduled_start"))
    task_type = values.get("task_type")
    if task_type is not None and not (
        isinstance(task_type, str) and 0 < len(task_type) <= TASK_TYPE_MAX
    ):
        problems.append(("task_type", "invalid_value"))
    return problems


def creates_loop[K: Hashable](
    edges: Mapping[K, Collection[K]], task: K, depends_on: Iterable[K]
) -> bool:
    """Whether `task` waiting for `depends_on` closes a loop (a task waits, at last, for itself)."""
    seen: set[K] = set()
    stack = list(depends_on)
    while stack:
        current = stack.pop()
        if current == task:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(edges.get(current, ()))
    return False


def open_predecessors(depends_on: Iterable[Any], statuses: Mapping[Any, str]) -> list[Any]:
    """The predecessors not yet finished (done or canceled), in the order given."""
    return [d for d in depends_on if statuses.get(d) not in FINISHED_STATUSES]


@dataclass(frozen=True)
class TaskSpec:
    """One task a template adds (title required; the rest optional)."""

    title: str
    description: str | None = None
    task_type: str | None = None
    priority: str = TaskPriority.NORMAL.value
    estimated_minutes: int | None = None
    # REQ-INC-040: only when the new record matches this filter DSL tree (None: always).
    condition: Any = None


def spec_of(raw: Mapping[str, Any]) -> TaskSpec | list[tuple[str, str]]:
    """One template task from JSON, or its problems (fields relative to the task)."""
    problems: list[tuple[str, str]] = []
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        problems.append(("title", "required"))
    elif len(title.strip()) > TITLE_MAX:
        problems.append(("title", "too_long"))
    description = raw.get("description")
    if description is not None and (
        not isinstance(description, str) or len(description) > DESCRIPTION_MAX
    ):
        problems.append(("description", "too_long"))
    priority = raw.get("priority", TaskPriority.NORMAL.value)
    if priority not in {p.value for p in TaskPriority}:
        problems.append(("priority", "invalid_choice"))
    problems += detail_problems({k: raw.get(k) for k in ("task_type", "estimated_minutes")})
    if problems:
        return problems
    assert isinstance(title, str)  # noqa: S101 - checked above
    return TaskSpec(
        title=title.strip(),
        description=description,
        task_type=raw.get("task_type"),
        priority=str(priority),
        estimated_minutes=raw.get("estimated_minutes"),
        condition=raw.get("condition"),
    )


def specs_of(raw: Any) -> list[TaskSpec] | list[tuple[str, str]]:  # noqa: ANN401 - JSON
    """A template's tasks (1-20), or problems as `tasks.<n>.<field>`."""
    if not isinstance(raw, list) or not raw:
        return [("tasks", "required")]
    if len(raw) > MAX_TEMPLATE_TASKS:
        return [("tasks", "too_many_items")]
    found: list[TaskSpec] = []
    problems: list[tuple[str, str]] = []
    for index, item in enumerate(raw):
        spec = spec_of(item if isinstance(item, dict) else {})
        if isinstance(spec, list):
            problems += [(f"tasks.{index}.{field}", code) for field, code in spec]
        else:
            found.append(spec)
    return problems or found


__all__ = [
    "FINISHED_STATUSES",
    "GATED_STATUSES",
    "MAX_DEPENDENCIES",
    "MAX_TEMPLATE_TASKS",
    "DependencyMode",
    "TaskSpec",
    "creates_loop",
    "detail_problems",
    "open_predecessors",
    "spec_of",
    "specs_of",
]
