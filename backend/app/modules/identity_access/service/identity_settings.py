"""A tenant's sign-in settings (WP-039, REQ-SEC-013, REQ-SEC-017, REQ-SEC-029; D-094).

Sessions: idle and absolute timeouts for the console and the portal, within Appendix A's caps.
A session takes its tenant's limits when it begins (sign-in or switching tenant), so a change
applies to every session begun after it; existing sessions keep the limits they began with
(never longer than the platform caps).

People creation: whether a first sign-in creates the person (default on, as requester; D-029
maps their starting role once). Off: only people an admin added, imported or invited sign in;
others are refused with "contact your service desk".

Password policy (session 2, REQ-SEC-005, domain/password_policy.py): installation-wide, so
editable only on single-tenant installations (`multi_tenant` off; otherwise the platform's,
`password_policy_platform`). A change sets `password_policy_state` to `applying` and emits
`identity_access.password_policy.changed`; the worker (service/password_policy.py) writes it
into the realm and records `applied` or `failed` with the reason.

Saving needs `identity.manage` and follows If-Match (version 0 = never saved); the route audits
it (`identity.settings_changed`, with the fields before and after). It emits
`identity_access.identity_settings.changed` (realtime: other admins' settings pages follow).
"""

from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, ValidationFailed
from app.modules.identity_access.domain import mobile as mobile_rules
from app.modules.identity_access.domain import password_policy as policy_rules
from app.modules.identity_access.events import IdentitySettingsChanged, PasswordPolicyChanged
from app.modules.identity_access.infra.models import (
    MAX_IDLE_SECONDS,
    MIN_IDLE_SECONDS,
    MOBILE_MAX_ABSOLUTE_SECONDS,
    SESSION_LIMITS,
    IdentitySettings,
)
from app.shared.events import record_event
from app.shared.history import stale_version

AppName = Literal["console", "portal"]
MIN_INVITATION_DAYS, MAX_INVITATION_DAYS = 1, 30  # Appendix A: 7 days, at most 30
MAX_MFA_GRACE_DAYS = 30  # Appendix A: 7 days, at most 30


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
    password_min_length: int = 12
    password_upper: bool = True
    password_lower: bool = True
    password_digits: bool = True
    password_special: bool = True
    password_history: int = 5
    password_expiry_days: int = 0
    password_breached_check: bool = True
    mfa_grace_days: int = 7  # REQ-SEC-024: days to enrol once MFA is required (0 to 30)
    # REQ-PRT-013 AC2 (WP-028): people edit their own phone and mobile (off: read-only).
    people_edit_contact: bool = False
    # REQ-INT-019, REQ-SEC-037 (D-128): people make keys for themselves; keys without expiry.
    people_may_create_keys: bool = False
    allow_non_expiring_keys: bool = False
    # WP-057 S4a (REQ-SEC-037): the key policy for new keys (older ones are flagged, not revoked).
    key_max_lifetime_days: int = 366
    keys_require_ip_range: bool = False
    key_unused_days: int = 90
    # REQ-SEC-047 (WP-057 S6b, 0206): the mobile app policy; no row, the defaults (lane B's
    # condition 2). Mobile limits None: the person's web app's limits.
    mobile_allowed: bool = True
    mobile_refusal_message: dict[str, str] | None = None
    mobile_mfa_required: bool = False
    mobile_device_unlock_required: bool = False
    mobile_unlock_after_minutes: int = 5
    mobile_idle_seconds: int | None = None
    mobile_absolute_seconds: int | None = None
    mobile_clear_on_sign_out: bool = True
    # Not edited: whether the worker has written the policy into the realm (models.py).
    password_policy_state: str = "default"  # noqa: S105 - a state code, not a password
    password_policy_error: str | None = None

    def password_policy(self) -> policy_rules.PasswordPolicy:
        """The password rules these settings hold."""
        return policy_rules.PasswordPolicy(
            **{rule: getattr(self, column) for rule, column in policy_rules.FIELDS.items()}
        )

    def session_limits(self, app: AppName) -> tuple[int, int]:
        """(idle, absolute) seconds for sessions of `app`."""
        if app == "console":
            return self.console_idle_seconds, self.console_absolute_seconds
        return self.portal_idle_seconds, self.portal_absolute_seconds

    def mobile_session_limits(self, app: AppName) -> tuple[int, int]:
        """(idle, absolute) seconds for a mobile session of `app`: the tenant's, else the web's."""
        if self.mobile_idle_seconds is None or self.mobile_absolute_seconds is None:
            return self.session_limits(app)
        return self.mobile_idle_seconds, self.mobile_absolute_seconds

    def mobile_policy(self) -> mobile_rules.MobilePolicy:
        """The mobile app policy these settings hold (REQ-SEC-047)."""
        return mobile_rules.MobilePolicy(
            allowed=self.mobile_allowed,
            refusal_message=self.mobile_refusal_message,
            mfa_required=self.mobile_mfa_required,
            device_unlock_required=self.mobile_device_unlock_required,
            unlock_after_minutes=self.mobile_unlock_after_minutes,
            clear_on_sign_out=self.mobile_clear_on_sign_out,
        )


DEFAULTS = IdentitySettingsView(
    console_idle_seconds=SESSION_LIMITS["console"]["idle"],
    console_absolute_seconds=SESSION_LIMITS["console"]["absolute"],
    portal_idle_seconds=SESSION_LIMITS["portal"]["idle"],
    portal_absolute_seconds=SESSION_LIMITS["portal"]["absolute"],
    create_people_on_sign_in=True,
    version=0,
)
STATE_FIELDS = ("version", "password_policy_state", "password_policy_error")
EDITABLE = tuple(f.name for f in fields(IdentitySettingsView) if f.name not in STATE_FIELDS)
PASSWORD_FIELDS = tuple(policy_rules.FIELDS.values())


async def get_identity_settings(session: AsyncSession) -> IdentitySettingsView:
    """The tenant's settings, or the defaults when never saved."""
    row = await session.scalar(select(IdentitySettings))
    if row is None:
        return DEFAULTS
    return IdentitySettingsView(
        **{name: getattr(row, name) for name in (*EDITABLE, *STATE_FIELDS)},
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
    errors += policy_rules.problems(values.password_policy())
    if not 0 <= values.mfa_grace_days <= MAX_MFA_GRACE_DAYS:
        errors.append(
            FieldError(
                field="mfa_grace_days",
                code="mfa_grace_out_of_range",
                message_key="errors.field.mfa_grace_out_of_range",
                params={"min": 0, "max": MAX_MFA_GRACE_DAYS},
            )
        )
    errors += _key_policy_problems(values)
    errors += _mobile_problems(values)
    if errors:
        raise ValidationFailed(errors=errors)


def _mobile_problems(values: IdentitySettingsView) -> list[FieldError]:
    """The mobile policy's bounds (0206's checks), each at its field with its limit."""
    errors = [
        FieldError(field=f"mobile_{name}", code=code, message_key=f"errors.field.mobile_{code}")
        for name, code in mobile_rules.policy_problems(
            {
                "unlock_after_minutes": values.mobile_unlock_after_minutes,
                "refusal_message": values.mobile_refusal_message,
            }
        )
    ]
    idle, absolute = values.mobile_idle_seconds, values.mobile_absolute_seconds
    if (idle is None) != (absolute is None):
        errors.append(
            FieldError(
                field="mobile_absolute_seconds",
                code="mobile_limits_both",
                message_key="errors.field.mobile_limits_both",
            )
        )
    elif idle is not None and absolute is not None:
        if not MIN_IDLE_SECONDS <= idle <= MAX_IDLE_SECONDS:
            errors.append(
                FieldError(
                    field="mobile_idle_seconds",
                    code="session_idle_out_of_range",
                    message_key="errors.field.session_idle_out_of_range",
                    params={"min": MIN_IDLE_SECONDS // 60, "max": MAX_IDLE_SECONDS // 60},
                )
            )
        if not idle <= absolute <= MOBILE_MAX_ABSOLUTE_SECONDS:
            errors.append(
                FieldError(
                    field="mobile_absolute_seconds",
                    code="session_absolute_out_of_range",
                    message_key="errors.field.session_absolute_out_of_range",
                    params={"max": MOBILE_MAX_ABSOLUTE_SECONDS // 3600},
                )
            )
    return errors


KEY_LIFETIME_DAYS = (1, 366)  # 0174's check
KEY_UNUSED_DAYS = (7, 365)  # 0174's check


def _key_policy_problems(values: IdentitySettingsView) -> list[FieldError]:
    """The key policy's ranges, each at its field with the range (REQ-SEC-037)."""
    errors: list[FieldError] = []
    for name, (low, high) in (
        ("key_max_lifetime_days", KEY_LIFETIME_DAYS),
        ("key_unused_days", KEY_UNUSED_DAYS),
    ):
        if not low <= getattr(values, name) <= high:
            errors.append(
                FieldError(
                    field=name,
                    code="days_out_of_range",
                    message_key="errors.field.days_out_of_range",
                    params={"min": low, "max": high},
                )
            )
    return errors


async def save_identity_settings(
    session: AsyncSession,
    values: IdentitySettingsView,
    *,
    expected_version: int,
    multi_tenant: bool = False,
) -> tuple[IdentitySettingsView, dict[str, object]]:
    """Save `values` (its version is ignored) if the stored version is `expected_version`.

    Returns the saved settings and, for the audit entry, each changed field before and after.
    """
    check_session_limits(values)
    current = await get_identity_settings(session)
    if current.version != expected_version:
        saved = await session.scalar(select(IdentitySettings))
        if saved is not None:
            raise await stale_version(session, saved, expected_version=expected_version)
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": current.version},
        )
    changed = [name for name in EDITABLE if getattr(current, name) != getattr(values, name)]
    if not changed:
        return current, {}
    policy_changed = any(name in PASSWORD_FIELDS for name in changed)
    if policy_changed and multi_tenant:
        raise Conflict(code="password_policy_platform")
    context = session.info[SESSION_TENANT_KEY]
    now = datetime.now(UTC)
    columns: dict[str, object] = {name: getattr(values, name) for name in EDITABLE}
    if policy_changed:
        columns |= {"password_policy_state": "applying", "password_policy_error": None}
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
    if policy_changed:
        await record_event(
            session,
            PasswordPolicyChanged(),
            aggregate_id=context.tenant_id,
            aggregate_version=version,
        )
    details: dict[str, object] = {"changed_fields": changed, "version": version}
    for name in changed:
        details[f"{name}.before"] = getattr(current, name)
        details[f"{name}.after"] = getattr(values, name)
    return await get_identity_settings(session), details


async def apply_password_policy_again(
    session: AsyncSession, *, multi_tenant: bool
) -> IdentitySettingsView:
    """Ask the worker to write the saved policy into the realm again (after `failed`)."""
    if multi_tenant:
        raise Conflict(code="password_policy_platform")
    row = await session.scalar(select(IdentitySettings).with_for_update())
    if row is None:  # never saved: the realm keeps the deploy's policy; save first
        raise Conflict(code="password_policy_not_saved")
    row.password_policy_state, row.password_policy_error = "applying", None
    await session.flush()
    await record_event(
        session, PasswordPolicyChanged(), aggregate_id=row.tenant_id, aggregate_version=row.version
    )
    await record_event(
        session,
        IdentitySettingsChanged(changed_fields=["password_policy_state"]),
        aggregate_id=row.tenant_id,
        aggregate_version=row.version,
    )
    return await get_identity_settings(session)


MOBILE_FIELDS = tuple(f.name for f in fields(IdentitySettingsView) if f.name.startswith("mobile_"))


@dataclass(frozen=True)
class MobileChange:
    """The Mobile card's fields, all of them, as sent (REQ-SEC-047)."""

    allowed: bool
    refusal_message: dict[str, str] | None
    mfa_required: bool
    device_unlock_required: bool
    unlock_after_minutes: int
    idle_seconds: int | None
    absolute_seconds: int | None
    clear_on_sign_out: bool


def _cleaned(messages: dict[str, str] | None) -> dict[str, str] | None:
    """Plain text per language; an empty one is dropped, so the built-in text shows."""
    if messages is None:
        return None
    kept = {k: mobile_rules.clean_message(v) for k, v in messages.items()}
    return {k: v for k, v in kept.items() if v} or None


async def save_mobile_policy(
    session: AsyncSession, change: MobileChange, *, expected_version: int
) -> tuple[IdentitySettingsView, dict[str, object]]:
    """Save the Mobile card's own fields only (lane B's S6b condition 1).

    Every other setting keeps its stored value, and the version guards the whole row, so a save
    from a stale card is refused (409) and never overwrites another card's values. The refusal
    messages are cleaned to plain text here, and again when shown (condition 3).
    """
    current = await get_identity_settings(session)
    values = replace(
        current,
        mobile_allowed=change.allowed,
        mobile_refusal_message=change.refusal_message,
        mobile_mfa_required=change.mfa_required,
        mobile_device_unlock_required=change.device_unlock_required,
        mobile_unlock_after_minutes=change.unlock_after_minutes,
        mobile_idle_seconds=change.idle_seconds,
        mobile_absolute_seconds=change.absolute_seconds,
        mobile_clear_on_sign_out=change.clear_on_sign_out,
    )
    # The bounds on what was sent (a message too long is refused, never cut), then cleaned.
    check_session_limits(values)
    values = replace(values, mobile_refusal_message=_cleaned(change.refusal_message))
    return await save_identity_settings(session, values, expected_version=expected_version)
