"""A change's risk assessment (WP-045b S1; REQ-CHG-057, -060).

The questionnaire is the change template's own or Appendix A's; answering it scores the change
and sets its calculated level, with the answers and the questionnaire version kept (a later
edit of the questionnaire never rescores it, REQ-CHG-057 AC3). An override (the chosen level
and its reason) goes through the change's own fields. Both through the work items service's
details path: one If-Match on the change, history and the change event as for any edit.
"""

import uuid
from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import Subject
from app.modules.work_items.domain import change_risk as rules
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItemTemplate
from app.modules.work_items.service import work_items as items
from app.shared.history import Source

CHANGE = TYPES[WorkItemTypeCode.CHANGE]


async def questionnaire(
    session: AsyncSession, subject: Subject, record_id: uuid.UUID
) -> rules.Questionnaire:
    """The questionnaire this change is assessed with: its template's, else Appendix A's."""
    record = await items.visible_record(session, subject, CHANGE, record_id)
    template = (
        await session.get(WorkItemTemplate, record.template_id)
        if record.template_id is not None
        else None
    )
    return rules.questionnaire_from(template.risk_questionnaire if template else None)


async def assess(  # noqa: PLR0913 - the answers and their context, explicit
    session: AsyncSession,
    subject: Subject,
    record_id: uuid.UUID,
    *,
    answers: Mapping[str, str],
    expected_version: int,
    source: Source,
) -> items.DetailsView:
    """Score the answers and set the change's calculated risk (If-Match on the change)."""
    asked = await questionnaire(session, subject, record_id)
    result, problems = rules.assess(asked, answers)
    if result is None:
        raise items.field_errors(problems)
    return await items.update_details(
        session,
        subject,
        CHANGE,
        record_id,
        expected_version=expected_version,
        values={
            "risk": result.level.value,
            "risk_score": result.score,
            "risk_answers": dict(result.answers),
            "risk_version": result.version,
        },
        source=source,
    )
