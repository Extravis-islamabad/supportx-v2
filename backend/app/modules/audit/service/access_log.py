"""The personal data access log (REQ-AUD-017; WP-057 S3b-1; lane B's conditions).

Who viewed or exported whose personal data, and the AI masking counts (REQ-AI-019). It records
code, never values: the fields viewed are field codes, the masking is counts per type.

- **On only when** the tenant turned it on (`audit_settings.personal_data_log`) and the plan has
  `personal_data_log` (Professional). Otherwise `record_access` writes nothing.
- **One view per 15 minutes**: a view of the same record (or person) by the same accessor in the
  same 15 minutes is written once (`dedupe_key`, unique per tenant), so live refetches and list
  re-renders never flood it. Exports and masking are written every time.
- **Append-only**: the app role may only insert and read. Rows leave through the migrator-owned
  `audit_purge_access()` (the daily purge; it computes the cutoff itself, at least 365 days) and,
  after #498, an erased person's delete (it checks `users.erased_at`).
- **Read** with `audit.view_personal_data_access` (api/routes.py); each query is itself audited.

One API for every writer: the people screens and exports here, ADR-047 §9's audit entry views
(lane B) and the AI masking counts (lane C's ai module).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.modules.audit.domain.catalogue import AuditActorType
from app.modules.audit.events import PersonalDataAccessRecorded
from app.modules.audit.infra.models import PersonalDataAccess
from app.modules.audit.service.settings import load_settings
from app.modules.licensing import Feature, has_feature
from app.shared.events import record_event
from app.shared.ids import new_id

AccessKind = Literal["view", "export", "ai_masking"]
BUCKET = timedelta(minutes=15)
PAGE = 200


@dataclass(frozen=True)
class Accessor:
    """Who looked: a person, an API key, an agent... (the audit log's actor kinds)."""

    type: AuditActorType
    id: uuid.UUID | None


def _bucket(at: datetime) -> int:
    return int(at.timestamp() // BUCKET.total_seconds())


async def log_enabled(session: AsyncSession) -> bool:
    """Whether this tenant logs personal data access now (its switch and its plan)."""
    tenant_id = session.info[SESSION_TENANT_KEY].tenant_id
    if not (await load_settings(session)).personal_data_log:
        return False
    return await has_feature(tenant_id, Feature.PERSONAL_DATA_LOG)


async def record_access(  # noqa: PLR0913 - who, whose, what and why, keyword-only
    session: AsyncSession,
    *,
    kind: AccessKind,
    purpose: str,
    subject_person_id: uuid.UUID | None = None,
    record: tuple[str, uuid.UUID] | None = None,
    fields: Sequence[str] = (),
    counts: dict[str, int] | None = None,
    client: str | None = None,
    accessor: Accessor | None = None,
    now: datetime | None = None,
) -> bool:
    """Log one access when the log is on; whether a row was written (False: off or deduplicated).

    `kind` is `view`, `export` or `ai_masking`; `purpose` a code naming the screen or job
    (`person_profile`, `people_export`, `audit_entry`, `ai_summary`...). Name the person, the
    record, or both. Nothing here ever carries a value. `accessor` defaults to the session's
    person (the system for a job).
    """
    if subject_person_id is None and record is None:
        msg = "an access names a person or a record"
        raise ValueError(msg)
    if not await log_enabled(session):
        return False
    if accessor is None:  # the request's own person (or the system for a job)
        context = session.info[SESSION_TENANT_KEY]
        accessor = (
            Accessor(AuditActorType.PERSON, context.user_id)
            if context.user_id is not None
            else Accessor(AuditActorType.SYSTEM, None)
        )
    at = now or datetime.now(UTC)
    record_type, record_id = record if record is not None else (None, None)
    dedupe = None
    if kind == "view":
        whose = f"{record_type}:{record_id}" if record_id else f"person:{subject_person_id}"
        dedupe = f"{accessor.type.value}:{accessor.id}:{whose}:{_bucket(at)}"[:120]
    statement = insert(PersonalDataAccess).values(
        tenant_id=session.info[SESSION_TENANT_KEY].tenant_id,
        id=new_id(),
        occurred_at=at,
        accessor_type=accessor.type.value,
        accessor_id=accessor.id,
        subject_person_id=subject_person_id,
        record_type=record_type,
        record_id=record_id,
        kind=kind,
        purpose=purpose,
        fields=sorted(set(fields)),
        counts=counts,
        client=client,
        dedupe_key=dedupe,
    )
    if dedupe is not None:
        statement = statement.on_conflict_do_nothing(
            index_elements=[PersonalDataAccess.tenant_id, PersonalDataAccess.dedupe_key],
            index_where=PersonalDataAccess.dedupe_key.is_not(None),
        )
    written = await session.scalar(statement.returning(PersonalDataAccess.id))
    if written is None:
        return False
    # Open access logs refetch (rule c): the kind only, never whose data or who looked.
    await record_event(
        session,
        PersonalDataAccessRecorded(kind=kind),
        aggregate_id=written,
    )
    return True


async def entries(  # noqa: PLR0913 - the person and the period's bounds, keyword-only
    session: AsyncSession,
    *,
    person: uuid.UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    before: datetime | None = None,
    limit: int = PAGE,
) -> list[PersonalDataAccess]:
    """Everyone who accessed `person`'s data in a period, newest first (REQ-AUD-017 AC2)."""
    statement = select(PersonalDataAccess).where(PersonalDataAccess.subject_person_id == person)
    if since is not None:
        statement = statement.where(PersonalDataAccess.occurred_at >= since)
    if until is not None:
        statement = statement.where(PersonalDataAccess.occurred_at < until)
    if before is not None:
        statement = statement.where(PersonalDataAccess.occurred_at < before)
    statement = statement.order_by(
        PersonalDataAccess.occurred_at.desc(), PersonalDataAccess.id.desc()
    ).limit(limit)
    return list(await session.scalars(statement))


_PURGE = text("SELECT audit_purge_access()")


async def purge(session: AsyncSession) -> int:
    """Entries past the tenant's audit retention go (lane B: the same retention as the log).

    The function computes the cutoff itself (at least 365 days): the app passes no date, so it
    can never empty the log early.
    """
    return int(await session.scalar(_PURGE) or 0)
