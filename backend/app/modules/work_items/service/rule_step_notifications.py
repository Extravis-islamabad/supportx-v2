"""The notice of a rule step that could not assign its person, for every record type (D-154).

D-154 "rules" (Haider, through the coordinator, 2026-11-10): an SLA escalation, business rule or
trigger that names a person who is inactive, Away or no longer in the step's group puts the
record in the group with nobody on it, and is never skipped silently. Its owner is told; with
no owner, or an inactive one, whoever manages that kind of step is.

One shared source for all work item types (the coordinator's call): incidents, service
requests, problems, changes and releases. A type's own source (WP-056 may add richer change
and release ones) does not repeat it. Each recipient's access is the record type's own
visibility, so a manager who cannot see the record is never told of it.
"""

import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import NotFound
from app.modules.identity_access import active_user_ids, subject_for, user_names, worker_policy
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.events import WorkItemAssigneeUnavailable
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.realtime import RECORD_KIND
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import (
    EventDefault,
    LabelRef,
    NotificationCategory,
    NotificationChannel,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

RECORD_TYPE = "rule_step"  # the area "Rules and escalations" on the rules screen
UNAVAILABLE = "rule_step.assignee_unavailable"
STEP_OWNER = "step_owner"
# Rules and triggers: automation.manage; a workflow step (#366): workflows.manage.
_STEP_MANAGERS = {"sla_escalation": "sla.manage", "workflow": "workflows.manage"}
_MANAGER_LIMIT = 200  # administrators told of one record
# Where each type's record opens in the console.
_LINKS: Mapping[str, str] = {
    WorkItemTypeCode.INCIDENT.value: "/incidents/",
    WorkItemTypeCode.SERVICE_REQUEST.value: "/requests/",
    WorkItemTypeCode.PROBLEM.value: "/problems/",
    WorkItemTypeCode.CHANGE.value: "/changes/",
    WorkItemTypeCode.RELEASE.value: "/releases/",
}

EVENTS: tuple[NotificationEvent, ...] = (
    NotificationEvent(
        UNAVAILABLE,
        NotificationCategory.ASSIGNMENT,
        EventDefault(
            enabled=True, recipients=(STEP_OWNER,), channels=(NotificationChannel.IN_APP,)
        ),
        variables=(
            Variable("unavailable.person", "notification_variable.unavailable.person"),
            Variable("unavailable.reason", "notification_variable.unavailable.reason"),
        ),
    ),
)
VARIABLES = (
    Variable("record.display_id", "notification_variable.record.display_id"),
    Variable("record.title", "notification_variable.record.title"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


def _uuid(value: object) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value else None


async def step_recipients(
    session: AsyncSession, payload: Mapping[str, object]
) -> frozenset[uuid.UUID]:
    """The step's owner while active, else the managers of that kind of step (D-154 rules)."""
    owner = _uuid(payload.get("owner_id"))
    if owner is not None and owner in await active_user_ids(session, [owner]):
        return frozenset({owner})
    tenant = session.info[SESSION_TENANT_KEY].tenant_id
    permission = _STEP_MANAGERS.get(str(payload.get("step")), "automation.manage")
    held = await worker_policy().holders(session, tenant, permission, limit=_MANAGER_LIMIT)
    return frozenset(user for user, _name in held)


class RuleStepNotifications:
    """`RecordSource` for the rule-step notice, on every work item type."""

    record_type = RECORD_TYPE
    channel_kind = RECORD_KIND
    events = EVENTS
    recipient_kinds = (STEP_OWNER,)
    variables = VARIABLES
    conditions: tuple[str, ...] = ()
    event_types = (WorkItemAssigneeUnavailable.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """One notice per event, whatever the record's type (built types only)."""
        known = {code.value for code in TYPES}
        return (UNAVAILABLE,) if envelope.payload.get("type") in known else ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The record now, who is told, and who could not be assigned and why."""
        del event_code
        payload = envelope.payload
        record = await session.scalar(
            select(WorkItem).where(
                WorkItem.id == uuid.UUID(str(payload["work_item_id"])),
                WorkItem.deleted_at.is_(None),
            )
        )
        if record is None or record.type not in _LINKS:
            return None
        person = str(payload["person_id"])
        link = f"{_LINKS[record.type]}{record.id}"
        variables: dict[str, VariableValue] = {
            "record.display_id": record.display_id,
            "record.title": record.subject,
            "record.link": link,
            "unavailable.person": (await user_names(session, [person])).get(person),
            "unavailable.reason": LabelRef(f"assignee_unavailable.{payload['reason']}"),
        }
        return RecordContext(
            record_id=record.id,
            display_id=record.display_id,
            link=link,
            public_link=None,
            variables=variables,
            public_variables={},  # staff-only: the person and reason never reach a portal
            relatives={STEP_OWNER: await step_recipients(session, payload)},
            conditions={},
            urgent=False,
            event_code=UNAVAILABLE,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """The record type's own visibility: told only if they may see the record."""
        record = await session.get(WorkItem, record_id)
        if record is None or record.deleted_at is not None:
            return RecordAccess.NONE
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id)
        try:
            await items.visible_record(
                session, subject, TYPES[WorkItemTypeCode(record.type)], record_id
            )
        except NotFound:
            return RecordAccess.NONE
        return RecordAccess.FULL


SOURCE = RuleStepNotifications()


def register() -> None:
    """Make rule steps notify (idempotent; called when work_items is imported)."""
    register_record_source(SOURCE)
