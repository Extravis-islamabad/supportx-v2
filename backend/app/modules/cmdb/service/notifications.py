"""Configuration item notifications on the engine (WP-053 S5d; REQ-CMDB-023 AC1).

- `cmdb_ci.state_changed`: a CI's state changed. Off until a tenant turns it on; its rule may
  test the new state, the type, the business impact and the criticality ("a production server's
  state becomes maintenance: tell its owner", AC1). One notice per change.

Recipients: the CI's owner, the members of its owner group and of its managed-by group. Each
one's access is their own (S3 condition 4): someone who may not see the CI (role scope, ADR-053
narrowing) gets nothing. Variables are the CI's display ID, name and state only, never a custom
value, so nothing a field access rule withholds (ADR-047) can reach a notice.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.modules.cmdb.events import CiUpdated
from app.modules.cmdb.infra.models import Ci, CiState
from app.modules.cmdb.service.realtime import RECORD_KIND
from app.modules.cmdb.service.refs import can_see
from app.modules.identity_access import subject_for
from app.modules.organization import users_in_groups
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import (
    EventDefault,
    LabelRef,
    Localised,
    NotificationCategory,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

RECORD_TYPE = "cmdb_ci"
STATE_CHANGED = "cmdb_ci.state_changed"
# Recipient kinds are labelled by code across every source: "owner" is the knowledge
# article's, so a CI's owner has its own (CI notifications, S5d).
OWNER = "ci_owner"
OWNER_GROUP = "owner_group"
MANAGED_BY_GROUP = "managed_by_group"
RECIPIENT_KINDS = (OWNER, OWNER_GROUP, MANAGED_BY_GROUP)
CONDITIONS = ("state_id", "type_id", "business_impact", "criticality")
VARIABLES = (
    Variable("record.display_id", "notification_variable.record.display_id"),
    Variable("record.title", "notification_variable.record.title"),
    Variable("record.status", "notification_variable.record.status"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)
EVENTS = (
    NotificationEvent(
        STATE_CHANGED,
        NotificationCategory.STATUS,
        EventDefault(enabled=False, recipients=(OWNER,)),
        public=False,
    ),
)


def _state_name(state: CiState | None) -> VariableValue:
    """A state by its label: a built-in one's own, a tenant's by the names they gave it."""
    if state is None:
        return None
    if state.built_in:
        return LabelRef(f"cmdb_ci_state.{state.api_name}")
    return Localised(texts=dict(state.names or {}), fallback=None)


async def _members(session: AsyncSession, group_id: uuid.UUID | None) -> frozenset[uuid.UUID]:
    if group_id is None:
        return frozenset()
    return frozenset(await session.scalars(users_in_groups(frozenset({group_id}))))


class CiNotifications:
    """`RecordSource` for configuration items."""

    record_type = RECORD_TYPE
    channel_kind = RECORD_KIND
    events = EVENTS
    recipient_kinds = RECIPIENT_KINDS
    variables = VARIABLES
    conditions = CONDITIONS
    event_types = (CiUpdated.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """A save that changed the state raises one notice, whatever else it changed."""
        changed = envelope.payload.get("changed_fields") or []
        return (STATE_CHANGED,) if "state_id" in changed else ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The CI as the notice shows it, and who it goes to now."""
        del event_code
        ci_id = uuid.UUID(str(envelope.payload["ci_id"]))
        record = await session.scalar(select(Ci).where(Ci.id == ci_id, Ci.deleted_at.is_(None)))
        if record is None:
            return None
        state = await session.get(CiState, record.state_id) if record.state_id else None
        values: dict[str, VariableValue] = {
            "record.display_id": record.display_id,
            "record.title": record.name,
            "record.status": _state_name(state),
            "record.link": f"/cmdb/{record.id}",
        }
        return RecordContext(
            record_id=record.id,
            display_id=record.display_id,
            link=f"/cmdb/{record.id}",
            variables=values,
            public_variables={},
            relatives={
                OWNER: frozenset({record.owner_user_id} if record.owner_user_id else ()),
                OWNER_GROUP: await _members(session, record.owner_group_id),
                MANAGED_BY_GROUP: await _members(session, record.managed_by_group_id),
            },
            conditions={
                "state_id": str(record.state_id) if record.state_id else None,
                "type_id": str(record.type_id),
                "business_impact": record.business_impact,
                "criticality": record.criticality,
            },
            changed_fields=tuple(envelope.payload.get("changed_fields") or ()),
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for someone who may see the CI now; nothing for anyone else."""
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id)
        seen = await can_see(session, subject, record_id)
        return RecordAccess.FULL if seen else RecordAccess.NONE


def register() -> None:
    """The CI notification source (module import)."""
    register_record_source(CiNotifications())
