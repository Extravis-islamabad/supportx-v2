"""Stages of work items (ADR-041; REQ-WI-026, REQ-REL-014..017). Pure domain code, no I/O.

A staged type (releases now, changes later) moves through ordered **stages**, each owning some of
the type's statuses. A record follows one **path** (the stages it takes, in order). Every move is
a listed **transition** from one status to another:

* to a status in the **same stage**: a status move;
* to a status in **another stage**: a stage move (backward, outcome or skip);
* reaching the stage's **completing** status moves on automatically to the first status of the
  next stage on the path, in the same save.

`system` statuses (approval outcomes) are never set by a person, a rule or a workflow: only the
system entry point the approvals code calls. The rail is computed from the record's stage entries.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.modules.work_items.domain.lifecycle import ReasonList, ReasonMode, StatusCategory

DEFAULT_PATH = "default"
FIRST_LIFECYCLE = 1  # session 1 ships one life cycle version (ADR-041 §10)


class SetBy(StrEnum):
    """Who may move a record into a status."""

    PERSON = "person"
    SYSTEM = "system"  # approval outcomes: only the approvals code (REQ-CHG-025 AC3, -052)


@dataclass(frozen=True)
class StageDef:
    """One stage of a staged type (seed data)."""

    code: str


@dataclass(frozen=True)
class StagedStatusDef:
    """A status of a staged type: its stage, category, and whether it completes the stage."""

    code: str
    stage: str
    category: StatusCategory
    colour: str
    completing: bool = False
    set_by: SetBy = SetBy.PERSON


@dataclass(frozen=True)
class PathDef:
    """A path: the stages a record takes, in order, some optional (REQ-CHG-027)."""

    code: str
    stages: tuple[str, ...]
    optional: frozenset[str] = frozenset()


@dataclass(frozen=True)
class StatusTransitionDef:
    """A listed move (ADR-041 §4); `path` None means on every path."""

    from_status: str
    to_status: str
    reason_mode: ReasonMode = ReasonMode.NONE
    reason_list: ReasonList | None = None
    permission: str | None = None  # an extra action permission (cancel, reopen)
    path: str | None = None
    # Fields this move asks for in its one dialog (REQ-CHG-026, REQ-INC-048).
    required_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class StageModel:
    """A type's stages, statuses, paths and transitions, checked once (seed or a tenant's edit)."""

    stages: tuple[StageDef, ...]
    statuses: tuple[StagedStatusDef, ...]
    paths: tuple[PathDef, ...]
    transitions: tuple[StatusTransitionDef, ...]
    _by_status: Mapping[str, StagedStatusDef] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Index the statuses, then refuse a model that breaks a rule."""
        object.__setattr__(self, "_by_status", {s.code: s for s in self.statuses})
        problems = model_problems(self)
        if problems:
            raise StageModelError(problems)

    def status(self, code: str) -> StagedStatusDef:
        """The status with this code (KeyError when unknown)."""
        return self._by_status[code]

    def path(self, code: str) -> PathDef:
        """The path with this code."""
        return next(p for p in self.paths if p.code == code)

    def statuses_of(self, stage: str) -> list[StagedStatusDef]:
        """A stage's statuses, in their seed order."""
        return [s for s in self.statuses if s.stage == stage]

    def first_status(self, stage: str) -> StagedStatusDef:
        """Where a record lands on entering the stage."""
        return self.statuses_of(stage)[0]

    def moves_from(self, status: str, path: str) -> list[StatusTransitionDef]:
        """The listed moves from a status on a path, to statuses on that path."""
        on_path = set(self.path(path).stages)
        return [
            t
            for t in self.transitions
            if t.from_status == status
            and (t.path is None or t.path == path)
            and self.status(t.to_status).stage in on_path
        ]

    def next_stage(self, stage: str, path: str) -> str | None:
        """The stage after `stage` on the path (None after the last)."""
        order = self.path(path).stages
        index = order.index(stage)
        return order[index + 1] if index + 1 < len(order) else None


class StageModelError(ValueError):
    """A stage model breaks a rule (each problem named)."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _stage_problems(model: StageModel) -> list[str]:
    stages = [s.code for s in model.stages]
    problems: list[str] = []
    for stage in stages:
        owned = [s for s in model.statuses if s.stage == stage]
        if not owned:
            problems.append(f"stage_without_statuses:{stage}")
        elif sum(s.completing for s in owned) != 1 and stage != stages[-1]:
            problems.append(f"stage_needs_one_completing_status:{stage}")
    problems.extend(
        f"status_in_unknown_stage:{s.code}" for s in model.statuses if s.stage not in stages
    )
    return problems


def _path_problems(model: StageModel) -> list[str]:
    stages = [s.code for s in model.stages]
    problems: list[str] = []
    for path in model.paths:
        if any(s not in stages for s in path.stages):
            problems.append(f"path_with_unknown_stage:{path.code}")
        if [s for s in stages if s in path.stages] != list(path.stages):
            problems.append(f"path_out_of_order:{path.code}")
    return problems


def model_problems(model: StageModel) -> list[str]:
    """Every rule a stage model breaks (ADR-041): empty when valid."""
    statuses = {s.code for s in model.statuses}
    return [
        *_stage_problems(model),
        *_path_problems(model),
        *(
            f"transition_with_unknown_status:{t.from_status}->{t.to_status}"
            for t in model.transitions
            if t.from_status not in statuses or t.to_status not in statuses
        ),
    ]


class MoveRefused(ValueError):
    """A move the model does not allow: `code` names why (a label key in the UI)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Move:
    """What a status change does: the statuses passed through, and the stages entered."""

    target: StagedStatusDef
    transition: StatusTransitionDef
    # The final status after any automatic advance from a completing status.
    landed: StagedStatusDef
    entered: tuple[str, ...]  # stages entered, in order (empty: same stage)


def plan_move(
    model: StageModel,
    *,
    current: str,
    target: str,
    path: str,
    system: bool = False,
) -> Move:
    """The move from `current` to `target` on `path`, or MoveRefused (ADR-041 §4, §8)."""
    transition = next((t for t in model.moves_from(current, path) if t.to_status == target), None)
    if transition is None:
        code = "stage_move_not_allowed"
        raise MoveRefused(code)
    target_status = model.status(target)
    if target_status.set_by == SetBy.SYSTEM and not system:
        code = "stage_status_system_only"
        raise MoveRefused(code)
    entered: list[str] = []
    if target_status.stage != model.status(current).stage:
        entered.append(target_status.stage)
    landed = target_status
    # A completing status moves on to the next stage on the path, in the same save.
    while landed.completing:
        following = model.next_stage(landed.stage, path)
        if following is None:
            break
        landed = model.first_status(following)
        entered.append(following)
    return Move(target_status, transition, landed, tuple(entered))


class RailState(StrEnum):
    """A stage's place on the rail (computed, never stored)."""

    DONE = "done"
    CURRENT = "current"
    SKIPPED = "skipped"
    FUTURE = "future"


@dataclass(frozen=True)
class Entry:
    """A stage entry as the rail needs it."""

    stage: str
    entered_at: datetime
    left_at: datetime | None


@dataclass(frozen=True)
class RailStage:
    """One stage on the rail, with its entries (going back shows more than one)."""

    stage: str
    state: RailState
    optional: bool
    entries: tuple[Entry, ...]


def rail(
    model: StageModel, *, path: str, current: str, entries: Iterable[Entry]
) -> list[RailStage]:
    """The rail for a record on `path`, now in stage `current` (ADR-041 §7)."""
    chosen = model.path(path)
    by_stage: dict[str, list[Entry]] = {}
    for entry in entries:
        by_stage.setdefault(entry.stage, []).append(entry)
    order: Sequence[str] = chosen.stages
    now = order.index(current) if current in order else -1
    # The furthest stage reached so far: stages before it never entered were skipped.
    reached = max([order.index(s) for s in by_stage if s in order] + [now])
    out: list[RailStage] = []
    for index, stage in enumerate(order):
        if stage == current:
            state = RailState.CURRENT
        elif stage in by_stage:
            state = RailState.DONE
        elif index < reached:
            state = RailState.SKIPPED
        else:
            state = RailState.FUTURE
        out.append(
            RailStage(
                stage,
                state,
                stage in chosen.optional,
                tuple(sorted(by_stage.get(stage, []), key=lambda e: e.entered_at)),
            )
        )
    return out
