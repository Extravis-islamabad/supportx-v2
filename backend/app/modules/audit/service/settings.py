"""Audit settings per tenant: defaults, limits and edits (D-074, D-076; file 11 Appendix A).

The row is created on the first change; until then the defaults apply. Every change is versioned
(If-Match) and is itself audited (`audit.settings_changed`), with old and new values.
"""

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, ValidationFailed, message_key_for
from app.modules.audit.domain.catalogue import ALWAYS_LOGGED_READS, DEFAULT_READS, ReadCategory
from app.modules.audit.events import AuditSettingsChanged
from app.modules.audit.infra.models import AuditSettings
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes, stale_version

SETTINGS_RECORD_TYPE = "audit_settings"

RETENTION_DEFAULT_DAYS = 3 * 365
RETENTION_MIN_DAYS = 365
RETENTION_MAX_DAYS = 10 * 365
READ_WINDOW_DEFAULT = 10
REFUSAL_THRESHOLD_DEFAULT = 10
REFUSAL_WINDOW_DEFAULT = 10
LIMITS: dict[str, tuple[int, int]] = {
    "retention_days": (RETENTION_MIN_DAYS, RETENTION_MAX_DAYS),
    "read_window_minutes": (1, 1440),
    "refusal_threshold": (3, 1000),
    "refusal_window_minutes": (1, 1440),
}

if TYPE_CHECKING:
    from app.core.tenancy import TenantContext


@dataclass(frozen=True)
class AuditSettingsView:
    """The tenant's effective settings (defaults until the first change)."""

    retention_days: int
    read_window_minutes: int
    refusal_threshold: int
    refusal_window_minutes: int
    read_categories: tuple[str, ...]
    version: int

    def values(self) -> dict[str, object]:
        """The editable values, for history and the audit entry."""
        return {
            "retention_days": self.retention_days,
            "read_window_minutes": self.read_window_minutes,
            "refusal_threshold": self.refusal_threshold,
            "refusal_window_minutes": self.refusal_window_minutes,
            "read_categories": list(self.read_categories),
        }


DEFAULTS = AuditSettingsView(
    retention_days=RETENTION_DEFAULT_DAYS,
    read_window_minutes=READ_WINDOW_DEFAULT,
    refusal_threshold=REFUSAL_THRESHOLD_DEFAULT,
    refusal_window_minutes=REFUSAL_WINDOW_DEFAULT,
    read_categories=tuple(sorted(c.value for c in DEFAULT_READS)),
    version=0,
)


def _view(row: AuditSettings | None) -> AuditSettingsView:
    if row is None:
        return DEFAULTS
    return AuditSettingsView(
        retention_days=row.retention_days,
        read_window_minutes=row.read_window_minutes,
        refusal_threshold=row.refusal_threshold,
        refusal_window_minutes=row.refusal_window_minutes,
        read_categories=tuple(sorted(row.read_categories)),
        version=row.version,
    )


async def load_settings(session: AsyncSession) -> AuditSettingsView:
    """The tenant's settings (defaults when never changed)."""
    row = await session.scalar(select(AuditSettings))
    return _view(row)


def _validate(changes: dict[str, object]) -> list[FieldError]:
    errors: list[FieldError] = []
    for name, value in changes.items():
        if name == "read_categories":
            assert isinstance(value, (list, tuple))  # noqa: S101 - typed by the API schema
            known = {c.value for c in ReadCategory}
            if not set(value) <= known:
                code = "read_category_unknown"
                errors.append(
                    FieldError(field=f"body.{name}", code=code, message_key=_field_key(code))
                )
            continue
        low, high = LIMITS[name]
        if not isinstance(value, int) or not low <= value <= high:
            code = "out_of_range"
            errors.append(
                FieldError(
                    field=f"body.{name}",
                    code=code,
                    message_key=_field_key(code),
                    params={"min": low, "max": high},
                )
            )
    return errors


def _field_key(code: str) -> str:
    return message_key_for(code).replace("errors.", "errors.field.", 1)


async def update_settings(
    session: AsyncSession, *, expected_version: int, changes: dict[str, object], source: Source
) -> tuple[AuditSettingsView, AuditSettingsView]:
    """Apply `changes` (If-Match `expected_version`; 0 = never changed). Returns (before, after).

    The audit log itself is always logged when read; that category cannot be switched off.
    """
    if "read_categories" in changes:
        categories = set(changes["read_categories"])  # type: ignore[call-overload]  # validated list
        categories |= {c.value for c in ALWAYS_LOGGED_READS}
        changes = {**changes, "read_categories": sorted(categories)}
    errors = _validate(changes)
    if errors:
        raise ValidationFailed(errors=errors)
    row = await session.scalar(select(AuditSettings).with_for_update())
    before = _view(row)
    if before.version != expected_version:
        if row is not None:
            raise await stale_version(session, row, expected_version=expected_version)
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": before.version},
        )
    after = replace(before, **changes, version=before.version + 1)  # type: ignore[arg-type]  # keys validated
    if after.values() == before.values():
        return before, before
    context: TenantContext = session.info[SESSION_TENANT_KEY]
    if row is None:
        row = AuditSettings(tenant_id=context.tenant_id)
        session.add(row)
    row.retention_days = after.retention_days
    row.read_window_minutes = after.read_window_minutes
    row.refusal_threshold = after.refusal_threshold
    row.refusal_window_minutes = after.refusal_window_minutes
    row.read_categories = list(after.read_categories)
    row.version = after.version
    row.updated_by = context.user_id
    await session.flush()
    old, new = before.values(), after.values()
    changed = [name for name in new if old[name] != new[name]]
    await record_changes(
        session,
        record_type=SETTINGS_RECORD_TYPE,
        record_id=context.tenant_id,
        version=after.version,
        kind="updated",
        changes=[Change(name, old[name], new[name]) for name in changed],
        source=source,
    )
    await record_event(
        session,
        AuditSettingsChanged(changed_fields=changed),
        aggregate_id=context.tenant_id,
        aggregate_version=after.version,
    )
    return before, after
