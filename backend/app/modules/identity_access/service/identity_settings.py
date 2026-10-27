"""A tenant's sign-in settings (WP-039, REQ-SEC-013, REQ-SEC-017, REQ-SEC-029; D-094).

Sessions: idle and absolute timeouts for the console and the portal, within Appendix A's caps.
A session takes its tenant's limits when it begins (sign-in or switching tenant), so a change
applies to every session begun after it; existing sessions keep the limits they began with
(never longer than the platform caps).

People creation: whether a first sign-in creates the person (default on, as requester; D-029
maps their starting role once). Off: only people an admin added, imported or invited sign in;
others are refused with "contact your service desk".

Saving needs `identity.manage` and follows If-Match (version 0 = never saved); the route audits
it (`identity.settings_changed`, with the fields before and after). It emits
`identity_access.identity_settings.changed` (realtime: other admins' settings pages follow).
"""

from dataclasses import dataclass, fields
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, ValidationFailed
from app.modules.identity_access.events import IdentitySettingsChanged
from app.modules.identity_access.infra.models import (
    MAX_IDLE_SECONDS,
    MIN_IDLE_SECONDS,
    SESSION_LIMITS,
    IdentitySettings,
)
from app.shared.events import record_event

AppName = Literal["console", "portal"]
MIN_INVITATION_DAYS, MAX_INVITATION_DAYS = 1, 30  # Appendix A: 7 days, at most 30


@dataclass(frozen=True)
class IdentitySettingsView:
    """The settings as shown (version 0: never saved, the defaults)."""

    console_idle_seconds: int
    console_absolute_seconds: int
    portal_idle_seconds: int
    portal_absolute_seconds: int
    create_people_on_sign_in: bool
    version: int
    invitation_valid_days: int = 7

    def session_limits(self, app: AppName) -> tuple[int, int]:
        """(idle, absolute) seconds for sessions of `app`."""
        if app == "console":
            return self.console_idle_seconds, self.console_absolute_seconds
        return self.portal_idle_seconds, self.portal_absolute_seconds


DEFAULTS = IdentitySettingsView(
    console_idle_seconds=SESSION_LIMITS["console"]["idle"],
    console_absolute_seconds=SESSION_LIMITS["console"]["absolute"],
    portal_idle_seconds=SESSION_LIMITS["portal"]["idle"],
    portal_absolute_seconds=SESSION_LIMITS["portal"]["absolute"],
    create_people_on_sign_in=True,
    version=0,
)
EDITABLE = tuple(f.name for f in fields(IdentitySettingsView) if f.name != "version")


async def get_identity_settings(session: AsyncSession) -> IdentitySettingsView:
    """The tenant's settings, or the defaults when never saved."""
    row = await session.scalar(select(IdentitySettings))
    if row is None:
        return DEFAULTS
    return IdentitySettingsView(
        console_idle_seconds=row.console_idle_seconds,
        console_absolute_seconds=row.console_absolute_seconds,
        portal_idle_seconds=row.portal_idle_seconds,
        portal_absolute_seconds=row.portal_absolute_seconds,
        create_people_on_sign_in=row.create_people_on_sign_in,
        version=row.version,
        invitation_valid_days=row.invitation_valid_days,
    )


def check_session_limits(values: IdentitySettingsView) -> None:
    """Refuse limits outside Appendix A's caps, each at its field with the limit (D-091)."""
    errors: list[FieldError] = []
    for app in ("console", "portal"):
        idle, absolute = values.session_limits(app)
        cap = SESSION_LIMITS[app]["max_absolute"]
        if not MIN_IDLE_SECONDS <= idle <= MAX_IDLE_SECONDS:
            errors.append(
                FieldError(
                    field=f"{app}_idle_seconds",
                    code="session_idle_out_of_range",
                    message_key="errors.field.session_idle_out_of_range",
                    params={"min": MIN_IDLE_SECONDS // 60, "max": MAX_IDLE_SECONDS // 60},
                )
            )
        if not idle <= absolute <= cap:
            errors.append(
                FieldError(
                    field=f"{app}_absolute_seconds",
                    code="session_absolute_out_of_range",
                    message_key="errors.field.session_absolute_out_of_range",
                    params={"max": cap // 3600},
                )
            )
    if not MIN_INVITATION_DAYS <= values.invitation_valid_days <= MAX_INVITATION_DAYS:
        errors.append(
            FieldError(
                field="invitation_valid_days",
                code="invitation_days_out_of_range",
                message_key="errors.field.invitation_days_out_of_range",
                params={"min": MIN_INVITATION_DAYS, "max": MAX_INVITATION_DAYS},
            )
        )
    if errors:
        raise ValidationFailed(errors=errors)


async def save_identity_settings(
    session: AsyncSession, values: IdentitySettingsView, *, expected_version: int
) -> tuple[IdentitySettingsView, dict[str, object]]:
    """Save `values` (its version is ignored) if the stored version is `expected_version`.

    Returns the saved settings and, for the audit entry, each changed field before and after.
    """
    check_session_limits(values)
    current = await get_identity_settings(session)
    if current.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": current.version},
        )
    changed = [name for name in EDITABLE if getattr(current, name) != getattr(values, name)]
    if not changed:
        return current, {}
    context = session.info[SESSION_TENANT_KEY]
    now = datetime.now(UTC)
    columns = {name: getattr(values, name) for name in EDITABLE}
    statement = (
        insert(IdentitySettings)
        .values(
            tenant_id=context.tenant_id,
            created_by=context.user_id,
            updated_by=context.user_id,
            version=1,
            **columns,
        )
        .on_conflict_do_update(
            index_elements=[IdentitySettings.tenant_id],
            set_={
                **columns,
                "updated_at": now,
                "updated_by": context.user_id,
                "version": IdentitySettings.version + 1,
            },
            where=IdentitySettings.version == expected_version,
        )
        .returning(IdentitySettings.version)
    )
    version = await session.scalar(statement)
    if version is None:  # changed by someone else between the read and the write
        raise Conflict(code="version_conflict", params={"expected_version": expected_version})
    await record_event(
        session,
        IdentitySettingsChanged(changed_fields=changed),
        aggregate_id=context.tenant_id,
        aggregate_version=version,
    )
    details: dict[str, object] = {"changed_fields": changed, "version": version}
    for name in changed:
        details[f"{name}.before"] = getattr(current, name)
        details[f"{name}.after"] = getattr(values, name)
    return await get_identity_settings(session), details
