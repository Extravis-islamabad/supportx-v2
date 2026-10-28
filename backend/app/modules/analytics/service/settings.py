"""Per-tenant report settings (parity file 09 Appendix A; D-041: every default is editable).

The row is created on first use with the shipped defaults; weeks start on Sunday when the
tenant's default site speaks Arabic, else on Monday (Appendix A). Platform maximums
(Settings.report_*) still cap what a tenant chooses.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import FieldError, PermissionDenied, ValidationFailed
from app.modules import organization
from app.modules.analytics.events import ReportSettingsChanged
from app.modules.analytics.infra.models import ReportSettings
from app.modules.identity_access import Subject
from app.shared.events import record_event
from app.shared.history import stale_version

if TYPE_CHECKING:
    from app.core.tenancy import TenantContext

MANAGE = "settings.manage"
WEEK_STARTS = ("monday", "sunday")
EDITABLE = ("week_start", "interactive_timeout_seconds", "export_link_days", "max_export_rows")


@dataclass(frozen=True)
class Limits:
    """What one run may use: the tenant's choice within the platform maximum."""

    week_start: str
    interactive_timeout_seconds: float
    export_link_days: int
    max_export_rows: int


async def tenant_settings(session: AsyncSession) -> ReportSettings:
    """The tenant's settings row, created with the defaults on first use."""
    row: ReportSettings | None = await session.scalar(select(ReportSettings))
    if row is not None:
        return row
    site = await organization.default_site(session)
    context: TenantContext = session.info["supportx.tenant"]
    await session.execute(
        insert(ReportSettings)
        .values(
            tenant_id=context.tenant_id,
            week_start="sunday" if site.default_language == "ar" else "monday",
        )
        .on_conflict_do_nothing()
    )
    found: ReportSettings | None = await session.scalar(select(ReportSettings))
    assert found is not None  # noqa: S101 - just inserted (or inserted by a concurrent request)
    return found


def limits_of(row: ReportSettings, platform: Settings) -> Limits:
    """The tenant's choices, capped by the platform maximums."""
    return Limits(
        week_start=row.week_start,
        interactive_timeout_seconds=min(
            float(row.interactive_timeout_seconds), platform.report_interactive_timeout_seconds
        ),
        export_link_days=row.export_link_days,
        max_export_rows=row.max_export_rows,
    )


def _check(values: Mapping[str, Any]) -> dict[str, Any]:
    ranges = {
        "interactive_timeout_seconds": (5, 60),
        "export_link_days": (1, 30),
        "max_export_rows": (1000, 1_000_000),
    }
    errors: list[FieldError] = []
    out: dict[str, Any] = {}
    for name, value in values.items():
        if name not in EDITABLE:
            continue
        if name == "week_start":
            if value not in WEEK_STARTS:
                errors.append(
                    FieldError(
                        field=f"body.{name}",
                        code="invalid_choice",
                        message_key="errors.field.invalid_choice",
                    )
                )
                continue
        else:
            low, high = ranges[name]
            if not isinstance(value, int) or not low <= value <= high:
                errors.append(
                    FieldError(
                        field=f"body.{name}",
                        code="out_of_range",
                        message_key="errors.field.out_of_range",
                        params={"min": low, "max": high},
                    )
                )
                continue
        out[name] = value
    if errors:
        raise ValidationFailed(errors=errors)
    return out


async def update_settings(
    session: AsyncSession,
    subject: Subject,
    values: Mapping[str, Any],
    *,
    expected_version: int,
) -> ReportSettings:
    """Change the fields given (If-Match on the version read); emits ReportSettingsChanged."""
    if not subject.holds(MANAGE):
        raise PermissionDenied(params={"permission": MANAGE})
    row = await tenant_settings(session)
    if row.version != expected_version:
        raise await stale_version(session, row, expected_version=expected_version)
    changes = {k: v for k, v in _check(values).items() if getattr(row, k) != v}
    if not changes:
        return row
    for name, value in changes.items():
        setattr(row, name, value)
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await record_event(
        session,
        ReportSettingsChanged(changed_fields=sorted(changes)),
        aggregate_id=row.tenant_id,
        aggregate_version=row.version,
    )
    return row
