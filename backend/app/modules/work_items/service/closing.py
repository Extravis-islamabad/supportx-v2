"""Resolving and closing in the one move path (WP-020f; REQ-INC-090, 093-095, 097).

`transition` calls `before_move` for every life-cycle move, so the record page, the API,
automation and later bulk and e-mail all obey the same closure rules and open-work checks.

Two ports for other modules:

* `register_open_work(kind, checker, completer)`: tasks, checklists and child incidents
  (WP-020e) and approvals (WP-030) report what is still open on a record;
* `register_requester_channel(name)` and `resolution_notified(...)`: a channel that really
  reaches requesters (WP-023 e-mail, WP-028 portal) says so, and tells this module when the
  requester was told of a resolution. Auto-close counts from that moment only (product owner,
  2026-10-28), and cannot be switched on while no channel reaches requesters.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, ValidationFailed
from app.modules import metadata
from app.modules.work_items.domain.closure import (
    ASKED_BY_MOVE,
    CLOSURE_CODE,
    RESOLUTION,
    OpenItem,
    OpenWorkKind,
    decide_open_work,
    missing_fields,
    open_work_modes,
)
from app.modules.work_items.domain.lifecycle import StatusCategory, WorkItemAction
from app.modules.work_items.domain.templates import PickList
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service.catalogue import Catalogue
from app.shared.history import Change
from app.shared.richtext import is_blank, sanitize_html

OpenWorkChecker = Callable[[AsyncSession, WorkItem], Awaitable[Sequence[OpenItem]]]
OpenWorkCompleter = Callable[[AsyncSession, WorkItem], Awaitable[None]]

_checkers: dict[OpenWorkKind, tuple[OpenWorkChecker, OpenWorkCompleter | None]] = {}
_requester_channels: set[str] = set()

# The moves this module looks at.
RESOLVE = WorkItemAction.RESOLVE
CLOSE = WorkItemAction.CLOSE
DONE_MOVES = frozenset({RESOLVE, CLOSE})
REOPENING = frozenset({WorkItemAction.REOPEN})


def register_open_work(
    kind: OpenWorkKind, checker: OpenWorkChecker, completer: OpenWorkCompleter | None = None
) -> None:
    """Report a kind of open work on a record (and, optionally, how to complete it)."""
    _checkers[kind] = (checker, completer)


def unregister_open_work(kind: OpenWorkKind) -> None:
    """Undo `register_open_work` (tests, module shutdown)."""
    _checkers.pop(kind, None)


def register_requester_channel(name: str) -> None:
    """A channel that really reaches requesters (e-mail, portal) is available."""
    _requester_channels.add(name)


def unregister_requester_channel(name: str) -> None:
    """Undo `register_requester_channel` (tests, a channel switched off)."""
    _requester_channels.discard(name)


def requester_channels() -> frozenset[str]:
    """Channels that can tell a requester of a resolution; none until WP-023/024/028."""
    return frozenset(_requester_channels)


async def open_items(session: AsyncSession, record: WorkItem) -> list[OpenItem]:
    """Everything still open on the record, from every registered kind."""
    items: list[OpenItem] = []
    for checker, _ in _checkers.values():
        items.extend(await checker(session, record))
    return items


@dataclass(frozen=True)
class MoveInput:
    """What a resolve or close brings with it."""

    resolution: str | None = None
    closure_code: str | None = None
    confirm_open_work: bool = False


@dataclass
class MoveStep:
    """What `before_move` adds to the move: record values and history lines."""

    changes: dict[str, Any] = field(default_factory=dict)
    history: list[Change] = field(default_factory=list)


def _refused(problems: Sequence[tuple[str, str, Mapping[str, Any]]]) -> ValidationFailed:
    """422 `closure_rules`: one field error per missing or wrong field (same codes as the UI)."""
    return ValidationFailed(
        code="closure_rules",
        errors=[
            FieldError(
                field=f"body.{name}",
                code=code,
                message_key=f"errors.field.{code}",
                params=dict(params),
            )
            for name, code, params in problems
        ],
    )


async def before_move(
    session: AsyncSession,
    cat: Catalogue,
    record: WorkItem,
    action: WorkItemAction,
    given: MoveInput,
) -> MoveStep:
    """Closure rules and open work for a resolve or close; clearing on reopen (REQ-INC-097)."""
    step = MoveStep()
    if action in REOPENING:
        # History keeps the earlier resolution and closure code; the next resolve asks again.
        step.changes.update({RESOLUTION: None, CLOSURE_CODE: None, "resolution_notified_at": None})
        return step
    if action not in DONE_MOVES:
        return step
    _check_rules(cat, record, action, given, step, custom_keys=await _custom_keys(session, record))
    await _check_open_work(session, cat, record, given, step)
    return step


def _check_rules(  # noqa: PLR0913 - the move and its context, explicit
    cat: Catalogue,
    record: WorkItem,
    action: WorkItemAction,
    given: MoveInput,
    step: MoveStep,
    *,
    custom_keys: frozenset[str],
) -> None:
    """The move's own field (resolution or closure code) and the closure rules (REQ-INC-094)."""
    problems: list[tuple[str, str, Mapping[str, Any]]] = []
    values: dict[str, Any] = {name: getattr(record, name, None) for name in _record_fields()}
    if action == RESOLVE:
        text = sanitize_html(given.resolution) if given.resolution else None
        if text is not None and not is_blank(text):
            step.changes.update({RESOLUTION: text, "resolution_notified_at": None})
            values[RESOLUTION] = text
    elif given.closure_code:
        if given.closure_code in cat.reason_codes(PickList.CLOSURE_CODE):
            step.changes[CLOSURE_CODE] = given.closure_code
            values[CLOSURE_CODE] = given.closure_code
        else:
            problems.append((CLOSURE_CODE, "invalid_choice", {}))
    required = _required(cat, action, custom_keys)
    record_code = "required_to_resolve" if action == RESOLVE else "required_to_close"
    named = {name for name, _, _ in problems}
    for name in missing_fields(required, values, record.custom or {}):
        if name in named:  # already wrong (an unknown closure code): one problem per field
            continue
        # The move asks for its own field; the rest are filled on the record first.
        asked = ASKED_BY_MOVE.get(action.value) == name
        problems.append((name, "required" if asked else record_code, {}))
    if problems:
        raise _refused(problems)


async def _check_open_work(
    session: AsyncSession, cat: Catalogue, record: WorkItem, given: MoveInput, step: MoveStep
) -> None:
    """Open work blocks, or needs an explicit confirmation that history records (REQ-INC-095)."""
    decision = decide_open_work(
        await open_items(session, record), open_work_modes(cat.closure.open_work)
    )
    if decision.blocking:
        raise Conflict(code="open_work_blocked", params=_listed(decision.blocking))
    if decision.to_confirm and not given.confirm_open_work:
        raise Conflict(code="open_work_unconfirmed", params=_listed(decision.to_confirm))
    if not decision.to_confirm:
        return
    # REQ-INC-095 AC4: the confirmation is in history, with the open items listed.
    step.history.append(Change("open_work_confirmed", None, [i.title for i in decision.to_confirm]))
    if cat.closure.complete_open_work:
        for kind in {i.kind for i in decision.to_confirm}:
            completer = _checkers.get(kind, (None, None))[1]
            if completer is not None:
                await completer(session, record)


def _listed(items: Sequence[OpenItem]) -> dict[str, str | int]:
    return {"count": len(items), "items": ", ".join(i.title for i in items)}


def _record_fields() -> tuple[str, ...]:
    return (
        RESOLUTION,
        CLOSURE_CODE,
        "category_id",
        "site_id",
        "department_id",
        "group_id",
        "technician_id",
        "impact",
        "urgency",
        "level",
        "description",
        "tags",
    )


async def _custom_keys(session: AsyncSession, record: WorkItem) -> frozenset[str]:
    return frozenset(await metadata.definitions(session, record.type))


def _required(cat: Catalogue, action: WorkItemAction, custom_keys: frozenset[str]) -> list[str]:
    """The rule's fields; a custom field removed since is not asked for (it cannot be filled)."""
    listed = cat.closure.resolve_requires if action == RESOLVE else cat.closure.close_requires
    return [
        name
        for name in listed
        if not name.startswith("custom.") or name.removeprefix("custom.") in custom_keys
    ]


async def missing_for(
    session: AsyncSession, cat: Catalogue, record: WorkItem, action: WorkItemAction
) -> list[str]:
    """Fields the record still lacks for a resolve or close (the move asks for its own)."""
    if action not in DONE_MOVES:
        return []
    values = {name: getattr(record, name, None) for name in _record_fields()}
    required = _required(cat, action, await _custom_keys(session, record))
    return missing_fields(required, values, record.custom or {})


async def resolution_notified(session: AsyncSession, record_id: uuid.UUID, at: datetime) -> bool:
    """The requester was told of the resolution (by a channel that reaches them).

    Stamps the moment once per resolution; auto-close counts from it. False when the record is
    no longer resolved or was already stamped (a second channel, a retry).
    """
    stamped = await session.execute(
        update(WorkItem)
        .where(
            WorkItem.id == record_id,
            WorkItem.status_category == StatusCategory.RESOLVED.value,
            WorkItem.resolution_notified_at.is_(None),
            WorkItem.deleted_at.is_(None),
        )
        .values(resolution_notified_at=at)
    )
    return bool(getattr(stamped, "rowcount", 0))
