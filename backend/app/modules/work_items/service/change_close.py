"""Close one change by its own close, from any flow (REQ-CHG-101 bulk; lane C's REQ-REL-052).

The change screen's close is the listed move from the change's current status that lands in
the closed status (directly, or through a completing status that moves on). Bulk close and a
closing release's "close the linked changes" both come here, so a change is closed one way
only: the person's permissions and stage access, the closing rules (the closure code), the
children and open-work checks, history and events. Nothing is bypassed and nothing is retried:
a refusal is raised as the change screen would raise it, and the caller reports it per change.
A caller closing several runs each in its own savepoint (`session.begin_nested()`), so one
refusal never undoes the others.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, PermissionDenied
from app.modules.identity_access import Subject
from app.modules.work_items.domain.changes import CLOSED_STATUS
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.service import closing
from app.modules.work_items.service import work_items as items
from app.shared.history import Source

# No move from where the change is lands in closed (not at its review yet, already closed or
# canceled). Labelled since REQ-CHG-101.
NOT_CLOSABLE = "not_closable_from_here"

CHANGE = TYPES[WorkItemTypeCode.CHANGE]


async def close_change(  # noqa: PLR0913 - the change, its version and the close's input, explicit
    session: AsyncSession,
    subject: Subject,
    change_id: uuid.UUID,
    *,
    expected_version: int,
    closure_code: str | None,
    source: Source,
    resolution: str | None = None,
    confirm_open_work: bool = False,
) -> items.WorkItemView:
    """Close one change as its own screen would, or raise that screen's refusal.

    Refusals, unchanged: hidden → NotFound; no close listed from here → Conflict NOT_CLOSABLE;
    a listed close the person may not run (their rights, the stage's access) → PermissionDenied
    `transition_not_allowed` with its reason; a stale version → 409; the closing rules → their
    field problems (`closure_code` required or not a choice); an open child or open work →
    its Conflict (warning-level open work too, unless confirmed: `confirm_open_work`, as the
    change screen's dialog asks).
    """
    panel = await items.stage_panel(session, subject, CHANGE, change_id)
    closing_move = next(
        (m for m in panel.moves if (m.lands_in or m.transition.to_status) == CLOSED_STATUS),
        None,
    )
    if closing_move is None:
        raise Conflict(code=NOT_CLOSABLE, params={"status": panel.record.status})
    if not closing_move.allowed:
        raise PermissionDenied(
            code="transition_not_allowed", params={"reason": closing_move.reason}
        )
    return await items.move_status(
        session,
        subject,
        CHANGE,
        change_id,
        target=closing_move.transition.to_status,
        expected_version=expected_version,
        reason_code=None,
        reason_text=None,
        source=source,
        closing_input=closing.MoveInput(
            resolution=resolution,
            closure_code=closure_code,
            confirm_open_work=confirm_open_work,
        ),
    )


__all__ = ["NOT_CLOSABLE", "close_change"]
