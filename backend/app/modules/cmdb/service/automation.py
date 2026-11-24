"""Configuration items as trigger sources and targets (WP-053 S5d; REQ-CMDB-023).

Registers the CI record type with automation: the fields rules may test and set, its facts, the
system's save path, who may view and edit it, and this module's events as trigger events.
Automation never reads CMDB tables itself (CLAUDE.md rule e).

The coordinator's and lane C's conditions:
- the CI offers its own six events, never a work item's (C1; `offered_events`);
- a relationship event carries nothing about the other end, so an end the rule's people may not
  see leaves no trace in the run or its history (C2, lane C's L4);
- a rule sets only `cis.RULE_SETTABLE`, anything else `field_not_settable` (C3);
- a CI has no templates, so CREATED never starts a workflow (`facts` carries no template_id).
"""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import automation
from app.modules.cmdb.domain.types import CiImpact
from app.modules.cmdb.events import CiCreated, CiUpdated, RelationshipsChanged
from app.modules.cmdb.infra.models import Ci
from app.modules.cmdb.service import cis
from app.modules.identity_access import Subject
from app.shared.events import EventEnvelope

RECORD_TYPE = "cmdb_ci"
STATE = "state_id"
OFFERED = frozenset(
    {
        automation.TriggerEvent.CREATED,
        automation.TriggerEvent.UPDATED,
        automation.TriggerEvent.STATUS_CHANGED,
        automation.TriggerEvent.RELATIONSHIP_ADDED,
        automation.TriggerEvent.RELATIONSHIP_REMOVED,
        automation.TriggerEvent.DOWNTIME_STARTED,
    }
)
_IMPACTS = frozenset(i.value for i in CiImpact)
_REF = automation.FieldKind.REFERENCE
# What rules may test; only `cis.RULE_SETTABLE` may be set. Nothing custom: a rule's notice could
# otherwise carry a value a field access rule withholds from its recipient (ADR-047).
FIELDS: Mapping[str, automation.RuleField] = {
    "name": automation.RuleField(automation.FieldKind.TEXT),
    "type_id": automation.RuleField(_REF),
    "state_id": automation.RuleField(_REF, settable=True),
    "site_id": automation.RuleField(_REF),
    "owner_user_id": automation.RuleField(_REF),
    "owner_group_id": automation.RuleField(_REF, settable=True),
    "managed_by_group_id": automation.RuleField(_REF, settable=True),
    "business_impact": automation.RuleField(
        automation.FieldKind.CODE, values=_IMPACTS, settable=True
    ),
    "criticality": automation.RuleField(automation.FieldKind.CODE, values=_IMPACTS, settable=True),
}
assert {k for k, f in FIELDS.items() if f.settable} == cis.RULE_SETTABLE  # noqa: S101 - one list
_RELATIONSHIP = {
    "added": automation.TriggerEvent.RELATIONSHIP_ADDED,
    "removed": automation.TriggerEvent.RELATIONSHIP_REMOVED,
}


async def _fields(_session: AsyncSession) -> Mapping[str, automation.RuleField]:
    return FIELDS


async def _check_values(session: AsyncSession, values: Mapping[str, Any]) -> Mapping[str, str]:
    """A saved trigger's set values, checked as a person's edit would be (field → problem)."""
    found: dict[str, str] = {}
    for key in ("business_impact", "criticality"):
        if values.get(key) is not None and values[key] not in _IMPACTS:
            found[key] = "invalid_choice"
    refs = {
        k: v
        for k, v in values.items()
        if k in {"state_id", "owner_group_id", "managed_by_group_id"}
    }
    found |= {p.field: p.code for p in await cis.reference_problems(session, refs)}
    return found


async def _facts(session: AsyncSession, ci_id: uuid.UUID) -> Mapping[str, Any] | None:
    """The CI as conditions see it: its own fields only, never a template (no workflow starts)."""
    record = await session.scalar(select(Ci).where(Ci.id == ci_id, Ci.deleted_at.is_(None)))
    if record is None:
        return None
    return {key: cis.json_value(getattr(record, key)) for key in FIELDS}


async def _apply(
    session: AsyncSession,
    ci_id: uuid.UUID,
    values: Mapping[str, Any],
    change: automation.AutomatedChange,
) -> list[str]:
    return await cis.automated_update(
        session, ci_id, values, automation_ref=change.ref, cause_id=change.cause_id
    )


async def _labels(
    session: AsyncSession, ci_ids: Sequence[uuid.UUID]
) -> Mapping[uuid.UUID, tuple[str, str]]:
    rows = await session.execute(select(Ci.id, Ci.display_id, Ci.name).where(Ci.id.in_(ci_ids)))
    return {row.id: (row.display_id, row.name) for row in rows}


async def _may_view(session: AsyncSession, subject: Subject, ci_id: uuid.UUID) -> bool:
    return await cis.may_view(session, subject, ci_id)


async def _may_edit(session: AsyncSession, subject: Subject, ci_id: uuid.UUID) -> bool:
    return await cis.may_edit(session, subject, ci_id)


async def read_event(
    _session: AsyncSession, envelope: EventEnvelope
) -> Sequence[automation.RecordEvent]:
    """A committed CMDB event as triggers see it: the CIs it touched (empty: nothing)."""
    payload = envelope.payload
    ci_id = uuid.UUID(str(payload["ci_id"]))
    if envelope.event_type == RelationshipsChanged.event_type:
        event = _RELATIONSHIP.get(str(payload.get("action")))
        if event is None:
            return []
        # Both ends, each on its own (lane C's (b)), and nothing about the other end on either
        # (C2): not its ID, its type or that it exists. Every end says only "relationships".
        ends = {ci_id, *(uuid.UUID(str(o)) for o in payload.get("other_ci_ids") or [])}
        return [
            automation.RecordEvent(RECORD_TYPE, end, event, changed=["relationships"])
            for end in sorted(ends, key=str)
        ]
    one = _one(envelope.event_type, payload, ci_id)
    return [] if one is None else [one]


def _one(
    event_type: str, payload: Mapping[str, Any], ci_id: uuid.UUID
) -> automation.RecordEvent | None:
    if event_type == CiCreated.event_type:
        return automation.RecordEvent(RECORD_TYPE, ci_id, automation.TriggerEvent.CREATED)
    if event_type == CiUpdated.event_type:
        changed = list(payload.get("changed_fields") or [])
        # A state change is its own event (the CI's "status"); its old value is not in the
        # event, so conditions on "changed from" see it as unknown, never as a guess.
        event = (
            automation.TriggerEvent.STATUS_CHANGED
            if STATE in changed
            else automation.TriggerEvent.UPDATED
        )
        return automation.RecordEvent(RECORD_TYPE, ci_id, event, changed=changed)
    return None


def register() -> None:
    """The CI record type and its event reader (module import)."""
    automation.register_record_type(
        automation.RecordType(
            code=RECORD_TYPE,
            fields=_fields,
            check_values=_check_values,
            facts=_facts,
            apply=_apply,
            may_view=_may_view,
            may_edit=_may_edit,
            labels=_labels,
            offered_events=OFFERED,
        )
    )
    automation.register_event_reader(
        (CiCreated.event_type, CiUpdated.event_type, RelationshipsChanged.event_type), read_event
    )
