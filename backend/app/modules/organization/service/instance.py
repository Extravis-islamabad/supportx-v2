"""The tenant's instance settings (WP-042; REQ-ADM-049, 050, 052).

Read by everyone signed in (screens use the defaults and the languages offered); changed by the
organisation's configure right (or settings.manage), with If-Match, history, audit (on the route)
and an outbox event that reaches every screen. The base currency, once set, changes only with an
explicit confirmation: amounts recorded later are in it.
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, PermissionDenied, ValidationFailed
from app.modules.organization.domain.instance import problems
from app.modules.organization.events import TenantSettingsChanged
from app.modules.organization.infra.models import TenantSettings
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

if TYPE_CHECKING:
    import uuid

CONFIGURE = ("config.organisation", "settings.manage")
EDITABLE = (
    "time_zone",
    "week_start",
    "date_format",
    "time_format",
    "country",
    "fiscal_year_start_month",
    "contact_email",
    "contact_phone",
    "base_currency",
    "languages",
    "default_language",
)


async def settings_row(session: AsyncSession) -> TenantSettings:
    """The tenant's settings, created with the defaults on first use."""
    found: TenantSettings | None = await session.scalar(select(TenantSettings))
    if found is not None:
        return found
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    await session.execute(insert(TenantSettings).values(tenant_id=tenant).on_conflict_do_nothing())
    created: TenantSettings | None = await session.scalar(select(TenantSettings))
    assert created is not None  # noqa: S101 - just inserted in this transaction
    return created


async def offered_languages(session: AsyncSession) -> tuple[tuple[str, ...], str]:
    """The languages the tenant offers and its default (for a person's effective language)."""
    found = await session.execute(select(TenantSettings.languages, TenantSettings.default_language))
    row = found.one_or_none()
    if row is None:
        return ("en", "ar", "ur"), "en"
    return tuple(row.languages), row.default_language


async def update_settings(  # noqa: PLR0913 - the change, its version and its context, explicit
    session: AsyncSession,
    subject: Any,  # noqa: ANN401 - identity_access's Subject
    values: dict[str, Any],
    *,
    expected_version: int,
    confirm_currency: bool,
    source: Source,
) -> TenantSettings:
    """Change the settings, all or nothing; each problem named at its field."""
    if not any(subject.holds(p) for p in CONFIGURE):
        raise PermissionDenied(params={"permission": CONFIGURE[0]})
    current = await settings_row(session)
    if current.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": current.version},
        )
    values = {k: v for k, v in values.items() if k in EDITABLE}
    if "languages" in values:
        values["languages"] = [lang for lang in ("en", "ar", "ur") if lang in values["languages"]]
    merged = {"languages": current.languages, **values}
    if "default_language" not in values and "languages" in values:
        merged["default_language"] = current.default_language
    found = problems(merged)
    if found:
        raise ValidationFailed(
            errors=[
                FieldError(field=f"body.{f}", code=c, message_key=f"errors.field.{c}")
                for f, c in found
            ]
        )
    changing_currency = (
        "base_currency" in values and values["base_currency"] != current.base_currency
    )
    if changing_currency and current.version > 1 and not confirm_currency:
        raise Conflict(code="currency_change_needs_confirmation")
    changes = [
        Change(k, getattr(current, k), v) for k, v in values.items() if getattr(current, k) != v
    ]
    if not changes:
        return current
    for key, value in values.items():
        setattr(current, key, value)
    current.version += 1
    current.updated_by = getattr(subject, "user_id", None)
    await record_changes(
        session,
        record_type="tenant_settings",
        record_id=current.tenant_id,
        version=current.version,
        kind="updated",
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        TenantSettingsChanged(
            version=current.version, changed_fields=sorted(c.field for c in changes)
        ),
        aggregate_id=current.tenant_id,
        aggregate_version=current.version,
    )
    await session.flush()
    return current
