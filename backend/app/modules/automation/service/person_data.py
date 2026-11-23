"""Automation's slice of a person's erasure (ADR-052 §4; D-171).

Their availability state and round-robin positions go for good (0166 lets the app delete the
availability); the business rules, triggers and workflows they own pass to the successor. An
owner here is only the person told when an assignment fails (service/assignment.py): nothing in
automation runs with a person's rights (workflows run as their own service identity), so nothing
needs pausing. IDs of theirs inside rule actions or workflow definitions stay: they point at the
person's anonymised row (ADR-052 §3 step 5), and at run time a step naming someone who has left
falls back to the group (work_items' `place_person`) or, for approvals, to the approval
administrators. Counts only.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.automation.infra.models import (
    AssignmentTurn,
    AutomationTrigger,
    BusinessRule,
    TechnicianAvailability,
    Workflow,
)
from app.modules.identity_access import ErasureBatch, register_person_data


async def _hand_over(
    session: AsyncSession,
    model: Any,  # noqa: ANN401 - a model with owner_id and version
    person_id: uuid.UUID,
    successor_id: uuid.UUID,
) -> int:
    rows = list(
        await session.scalars(select(model).where(model.owner_id == person_id).with_for_update())
    )
    for row in rows:
        row.owner_id = successor_id
        row.version += 1
    await session.flush()
    return len(rows)


class Automation:
    """`automation`: their own rows go, what they own passes on (band 500-599)."""

    module: ClassVar[str] = "automation"
    order: ClassVar[int] = 580
    kinds: ClassVar[frozenset[str]] = frozenset(
        {
            "availability_deleted",
            "assignment_turns_deleted",
            "rules_handed_over",
            "triggers_handed_over",
            "workflows_handed_over",
        }
    )

    async def erase_person(  # noqa: PLR0913 - the port contract
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """All at once: a person has one availability row and few owned rules (no cursor)."""
        del keep_files, now, cursor  # no files, no times, no batches
        availability = await session.execute(
            delete(TechnicianAvailability).where(TechnicianAvailability.user_id == person_id)
        )
        turns = await session.execute(
            delete(AssignmentTurn).where(AssignmentTurn.user_id == person_id)
        )
        counts = {
            "availability_deleted": int(getattr(availability, "rowcount", 0) or 0),
            "assignment_turns_deleted": int(getattr(turns, "rowcount", 0) or 0),
            "rules_handed_over": await _hand_over(session, BusinessRule, person_id, successor_id),
            "triggers_handed_over": await _hand_over(
                session, AutomationTrigger, person_id, successor_id
            ),
            "workflows_handed_over": await _hand_over(session, Workflow, person_id, successor_id),
        }
        return ErasureBatch({k: v for k, v in counts.items() if v})


PORT = Automation()


def register() -> None:
    """At import (the registry refuses the job while it is missing)."""
    register_person_data(PORT)
