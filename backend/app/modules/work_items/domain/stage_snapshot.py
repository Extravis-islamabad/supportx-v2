"""A request's approval stages as snapshotted at submission (WP-047a S2a).

Pure: no I/O. Kept in `work_items.approval_stages` so a later change to the item never moves a
request already in flight. The coordinator's snapshot conditions:

1. Configuration only: kind and rule codes, IDs, switches and the condition. Never a name or an
   e-mail address (people are resolved when a stage opens).
2. The person IDs it holds (named approvers, backups) are covered by the ADR-052 erasure port.
3. A version key and a shape check: a stored value of another version or shape is refused
   rather than guessed at.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

VERSION = 1
KINDS = frozenset(
    {
        "person",
        "requested_for_manager",
        "manager_of_manager",
        "department_head",
        "group_leads",
        "group",
        "person_answer",
        "asset_owner",
        "ci_owner",
    }
)
RULES = frozenset({"any", "all", "majority"})
DEFAULT_RULE = "any"
SWITCHES = (
    "comments_required",
    "self_approval",
)  # a stage's yes/no settings
_APPROVER_KEYS = frozenset({"kind", "person_id", "group_id", "question_key"})
_STAGE_KEYS = frozenset(
    {
        "approvers",
        "rule",
        "backup_id",
        "comments_required",
        "self_approval",
        "parallel_group",
        "condition",
    }
)


class SnapshotShapeError(ValueError):
    """A stored snapshot that is not version 1's shape (never guessed at)."""


@dataclass(frozen=True)
class SnapApprover:
    """One approver as snapshotted: a kind code and the ID or question it names."""

    kind: str
    person_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    question_key: str | None = None


@dataclass(frozen=True)
class SnapStage:
    """One stage as snapshotted: its approvers, rule, backup, switches and condition."""

    approvers: tuple[SnapApprover, ...]
    rule: str = "any"
    backup_id: uuid.UUID | None = None
    comments_required: bool = False
    self_approval: bool = False
    parallel_group: str | None = None
    condition: Mapping[str, Any] | None = None


def _id(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)


def to_json(stages: Sequence[SnapStage]) -> dict[str, Any]:
    """The stored value: `{"v": 1, "stages": [...]}`, IDs as text, empty parts left out."""

    def approver(a: SnapApprover) -> dict[str, Any]:
        raw = {
            "kind": a.kind,
            "person_id": _id(a.person_id),
            "group_id": _id(a.group_id),
            "question_key": a.question_key,
        }
        return {k: v for k, v in raw.items() if v is not None}

    def stage(s: SnapStage) -> dict[str, Any]:
        raw: dict[str, Any] = {
            "approvers": [approver(a) for a in s.approvers],
            "rule": s.rule,
            "backup_id": _id(s.backup_id),
            "comments_required": s.comments_required,
            "self_approval": s.self_approval,
            "parallel_group": s.parallel_group,
            "condition": dict(s.condition) if s.condition is not None else None,
        }
        return {k: v for k, v in raw.items() if v is not None}

    return {"v": VERSION, "stages": [stage(s) for s in stages]}


def _uuid_problem(raw: Mapping[str, Any], key: str) -> bool:
    value = raw.get(key)
    if value is None:
        return False
    try:
        uuid.UUID(str(value))
    except ValueError:
        return True
    return not isinstance(value, str)


def problems(raw: object) -> list[str]:  # noqa: C901 - one check per part, flat
    """What is wrong with a stored snapshot's shape (empty: it is version 1's)."""
    if not isinstance(raw, Mapping):
        return ["not_an_object"]
    if raw.get("v") != VERSION:
        return ["unknown_version"]
    if set(raw) != {"v", "stages"} or not isinstance(raw["stages"], list):
        return ["bad_shape"]
    found: list[str] = []
    for n, stage in enumerate(raw["stages"]):
        at = f"stages.{n}"
        if not isinstance(stage, Mapping) or not set(stage) <= _STAGE_KEYS:
            found.append(at)
            continue
        if stage.get("rule", DEFAULT_RULE) not in RULES or _uuid_problem(stage, "backup_id"):
            found.append(at)
        if not isinstance(stage.get("approvers"), list):
            found.append(f"{at}.approvers")
            continue
        for i, a in enumerate(stage["approvers"]):
            if (
                not isinstance(a, Mapping)
                or not set(a) <= _APPROVER_KEYS
                or a.get("kind") not in KINDS
                or _uuid_problem(a, "person_id")
                or _uuid_problem(a, "group_id")
            ):
                found.append(f"{at}.approvers.{i}")
        found += [
            f"{at}.{flag}" for flag in SWITCHES if not isinstance(stage.get(flag, False), bool)
        ]
        if stage.get("condition") is not None and not isinstance(stage["condition"], Mapping):
            found.append(f"{at}.condition")
    return found


def from_json(raw: object) -> tuple[SnapStage, ...]:
    """The stored snapshot read back; SnapshotShapeError when it is not version 1's shape."""
    if found := problems(raw):
        raise SnapshotShapeError(", ".join(found))
    assert isinstance(raw, Mapping)  # noqa: S101 - narrowed by problems()

    def uid(value: object) -> uuid.UUID | None:
        return None if value is None else uuid.UUID(str(value))

    return tuple(
        SnapStage(
            approvers=tuple(
                SnapApprover(
                    a["kind"],
                    uid(a.get("person_id")),
                    uid(a.get("group_id")),
                    a.get("question_key"),
                )
                for a in s["approvers"]
            ),
            rule=s.get("rule", DEFAULT_RULE),
            backup_id=uid(s.get("backup_id")),
            comments_required=s.get("comments_required", False),
            self_approval=s.get("self_approval", False),
            parallel_group=s.get("parallel_group"),
            condition=s.get("condition"),
        )
        for s in raw["stages"]
    )


def person_ids(stages: Sequence[SnapStage]) -> set[uuid.UUID]:
    """Every person the snapshot names (named approvers and backups), for the erasure port."""
    found = {a.person_id for s in stages for a in s.approvers if a.person_id is not None}
    return found | {s.backup_id for s in stages if s.backup_id is not None}


def without_person(stages: Sequence[SnapStage], person: uuid.UUID) -> tuple[SnapStage, ...]:
    """The snapshot with an erased person's ID removed (ADR-052).

    Their named approver rows go and a backup they were is cleared. A stage left with no
    approver falls back to the approval administrators when it opens (the coordinator's S2
    condition 3), so nothing else changes.
    """
    return tuple(
        SnapStage(
            approvers=tuple(a for a in s.approvers if a.person_id != person),
            rule=s.rule,
            backup_id=None if s.backup_id == person else s.backup_id,
            comments_required=s.comments_required,
            self_approval=s.self_approval,
            parallel_group=s.parallel_group,
            condition=s.condition,
        )
        for s in stages
    )
