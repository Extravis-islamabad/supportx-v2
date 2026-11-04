"""The tenant's AI settings (REQ-AI-027, 031).

The master switch, feature switches, masking of local calls and how long call text is kept. Read
by everyone signed in (screens hide what is off); changed by `ai.manage`, with If-Match, history,
audit (on the route) and an outbox event.
"""

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, PermissionDenied, ValidationFailed
from app.modules.ai.domain.features import BY_CODE, INDEX_FEATURE
from app.modules.ai.events import AiSettingsChanged
from app.modules.ai.infra.models import AiEmbedding, AiSettings
from app.modules.ai.service.conversations import DEFAULT_SUMMARY_SOURCES, SUMMARY_SOURCES
from app.modules.audit import WORKER, record
from app.modules.identity_access import Subject
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

MANAGE = "ai.manage"
RETENTION_DAYS = range(1, 366)
EDITABLE = (
    "enabled",
    "disabled_features",
    "mask_local",
    "log_retention_days",
    "summary_sources",
)


def session_tenant(session: AsyncSession) -> uuid.UUID:
    """The tenant this session runs as (set with `app.tenant_id`)."""
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant


async def settings_row(session: AsyncSession) -> AiSettings:
    """The tenant's AI settings, created with the defaults on first use."""
    found: AiSettings | None = await session.scalar(select(AiSettings))
    if found is not None:
        return found
    await session.execute(
        insert(AiSettings).values(tenant_id=session_tenant(session)).on_conflict_do_nothing()
    )
    created: AiSettings | None = await session.scalar(select(AiSettings))
    assert created is not None  # noqa: S101 - just inserted in this transaction
    return created


async def _purge_embeddings(session: AsyncSession, subject: Subject) -> None:
    """AI or possible duplicates switched off: no AI data kept around (D-134), audited."""
    removed = await session.execute(delete(AiEmbedding))
    count = int(getattr(removed, "rowcount", 0) or 0)
    if count:
        await record(
            session,
            action_code="ai.embeddings_purged",
            facts=WORKER,
            object_type="ai_settings",
            object_id=subject.tenant_id,
            details={"embeddings": count},
        )


def summary_sources(settings: AiSettings) -> tuple[str, ...]:
    """What summaries read: the admin's choice, else the default (applied at read time)."""
    chosen = settings.summary_sources
    return tuple(chosen) if chosen is not None else DEFAULT_SUMMARY_SOURCES


def feature_on(settings: AiSettings, code: str) -> bool:
    """Whether a feature may run: AI on and the feature not switched off."""
    return settings.enabled and code not in settings.disabled_features


def _problem(field: str, code: str) -> FieldError:
    return FieldError(field=f"body.{field}", code=code, message_key=f"errors.field.{code}")


def _check(values: dict[str, Any]) -> list[FieldError]:
    """Each value's problem, named at its field; normalises the lists in place."""
    problems: list[FieldError] = []
    if "disabled_features" in values:
        codes = sorted(set(values["disabled_features"]))
        if any(code not in BY_CODE for code in codes):
            problems.append(_problem("disabled_features", "ai_feature_unknown"))
        values["disabled_features"] = codes
    if "log_retention_days" in values and values["log_retention_days"] not in RETENTION_DAYS:
        problems.append(_problem("log_retention_days", "ai_retention_out_of_range"))
    if "summary_sources" in values:
        chosen = set(values["summary_sources"])
        if not chosen <= set(SUMMARY_SOURCES):
            problems.append(_problem("summary_sources", "ai_summary_source_unknown"))
        elif not chosen:
            problems.append(_problem("summary_sources", "ai_summary_sources_empty"))
        values["summary_sources"] = [x for x in SUMMARY_SOURCES if x in chosen]
    return problems


async def update_settings(
    session: AsyncSession,
    subject: Subject,
    values: dict[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> AiSettings:
    """Change the AI settings, all or nothing; each problem named at its field."""
    if not subject.holds(MANAGE):
        raise PermissionDenied(params={"permission": MANAGE})
    current = await settings_row(session)
    if current.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": current.version},
        )
    values = {k: v for k, v in values.items() if k in EDITABLE}
    problems = _check(values)
    if problems:
        raise ValidationFailed(errors=problems)
    changes = [
        Change(k, getattr(current, k), v) for k, v in values.items() if getattr(current, k) != v
    ]
    if not changes:
        return current
    indexed_before = feature_on(current, INDEX_FEATURE)
    for key, value in values.items():
        setattr(current, key, value)
    if indexed_before and not feature_on(current, INDEX_FEATURE):
        await _purge_embeddings(session, subject)
    current.version += 1
    current.updated_by = subject.user_id
    await record_changes(
        session,
        record_type="ai_settings",
        record_id=current.tenant_id,
        version=current.version,
        kind="updated",
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        AiSettingsChanged(changed_fields=sorted(c.field for c in changes)),
        aggregate_id=current.tenant_id,
        aggregate_version=current.version,
    )
    await session.flush()
    return current
