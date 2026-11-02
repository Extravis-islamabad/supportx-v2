"""Article types on the knowledge settings page (WP-033 session 3b, D-120; REQ-KB-090).

Admins add their own types (names in English and Arabic, a review interval) and change, retire
or restore them. A built-in type is named by its label, so its names never change; its review
interval does, and it can be retired like any other. A retired type is never offered for a new
article; articles that have it keep it.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, ParamValue, ValidationFailed
from app.modules.identity_access import Subject
from app.modules.knowledge.events import KbTypeSaved
from app.modules.knowledge.infra.models import KbType
from app.modules.knowledge.service.access import MANAGE_TYPES, require
from app.modules.knowledge.service.articles import article_types
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

RECORD_TYPE = "kb_type"
NAME_MAX = 60
REQUIRED_NAMES = ("en", "ar")  # rule d: English and Arabic at MVP; Urdu optional (D-108 (6))
NAME_LANGUAGES = ("en", "ar", "ur")
REVIEW_MONTHS = range(1, 61)
TYPES_MAX = 50


def _problem(field: str, code: str, **params: ParamValue) -> FieldError:
    return FieldError(
        field=f"body.{field}", code=code, message_key=f"errors.field.{code}", params=params
    )


def clean_names(names: dict[str, str]) -> tuple[dict[str, str], list[FieldError]]:
    """Trimmed names in the known languages, plus problems (English and Arabic required)."""
    cleaned = {k: " ".join(v.split()) for k, v in names.items() if k in NAME_LANGUAGES}
    problems = [
        _problem(f"names.{k}", "value_too_long", max=NAME_MAX)
        for k, v in cleaned.items()
        if len(v) > NAME_MAX
    ]
    problems += [_problem(f"names.{k}", "required") for k in REQUIRED_NAMES if not cleaned.get(k)]
    return {k: v for k, v in cleaned.items() if v}, problems


def _months_problems(value: Any) -> list[FieldError]:  # noqa: ANN401 - checked here
    if not isinstance(value, int) or isinstance(value, bool) or value not in REVIEW_MONTHS:
        return [_problem("review_months", "out_of_range", min=1, max=60)]
    return []


def _record_id(code: str) -> uuid.UUID:
    # kb_types is keyed by (tenant, code): a stable id for its history and events.
    return uuid.uuid5(uuid.NAMESPACE_URL, f"kb_type:{code}")


async def _history_and_event(
    session: AsyncSession,
    kind: KbType,
    changes: list[Change],
    *,
    created: bool,
    source: Source,
) -> None:
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=_record_id(kind.code),
        version=kind.version,
        kind="created" if created else "updated",
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        KbTypeSaved(
            code=kind.code, created=created, changed_fields=sorted(c.field for c in changes)
        ),
        aggregate_id=_record_id(kind.code),
        aggregate_version=kind.version,
    )


async def create_type(
    session: AsyncSession, subject: Subject, values: dict[str, Any], *, source: Source
) -> KbType:
    """A new custom type (needs `knowledge.manage_types`)."""
    require(subject, MANAGE_TYPES)
    existing = await article_types(session)  # seeds the built-in ones on first use
    names, problems = clean_names(dict(values.get("names") or {}))
    problems += _months_problems(values.get("review_months"))
    if len(existing) >= TYPES_MAX:
        problems.append(_problem("names", "too_many_items", max=TYPES_MAX))
    if problems:
        raise ValidationFailed(errors=problems)
    order = await session.scalar(select(func.coalesce(func.max(KbType.sort_order), 0)))
    kind = KbType(
        tenant_id=existing[0].tenant_id if existing else _tenant(session),
        code=f"custom_{uuid.uuid4().hex[:12]}",
        names=names,
        review_months=values["review_months"],
        builtin=False,
        sort_order=int(order or 0) + 1,
        version=1,
        updated_by=subject.user_id,
    )
    session.add(kind)
    await session.flush()
    changes = [Change("names", None, names), Change("review_months", None, kind.review_months)]
    await _history_and_event(session, kind, changes, created=True, source=source)
    return kind


async def update_type(  # noqa: PLR0913, C901 - the If-Match and the source; one rule per field
    session: AsyncSession,
    subject: Subject,
    code: str,
    values: dict[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> KbType:
    """Change a type with If-Match: names (custom types only), review interval, retired."""
    require(subject, MANAGE_TYPES)
    await article_types(session)
    kind: KbType | None = await session.scalar(
        select(KbType).where(KbType.code == code).with_for_update()
    )
    if kind is None:
        raise NotFound(code="kb_type_not_found")
    if kind.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": kind.version},
        )
    problems: list[FieldError] = []
    wanted: dict[str, Any] = {}
    if "names" in values:
        if kind.builtin:
            problems.append(_problem("names", "builtin_type_names"))
        else:
            names, name_problems = clean_names(dict(values["names"] or {}))
            problems += name_problems
            wanted["names"] = names
    if "review_months" in values:
        problems += _months_problems(values["review_months"])
        wanted["review_months"] = values["review_months"]
    if "retired" in values:
        wanted["retired"] = bool(values["retired"])
    if problems:
        raise ValidationFailed(errors=problems)
    before = {
        "names": dict(kind.names),
        "review_months": kind.review_months,
        "retired": kind.retired_at is not None,
    }
    changes = [Change(k, before[k], v) for k, v in wanted.items() if before[k] != v]
    if not changes:
        return kind
    if "names" in wanted:
        kind.names = wanted["names"]
    if "review_months" in wanted:
        kind.review_months = wanted["review_months"]
    if "retired" in wanted:
        kind.retired_at = datetime.now(UTC) if wanted["retired"] else None
    kind.version += 1
    kind.updated_by = subject.user_id
    await session.flush()
    await _history_and_event(session, kind, changes, created=False, source=source)
    return kind


def _tenant(session: AsyncSession) -> uuid.UUID:
    from app.core.database import SESSION_TENANT_KEY  # noqa: PLC0415 - session info key

    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant
