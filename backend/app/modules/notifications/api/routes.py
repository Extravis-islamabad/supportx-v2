"""Notifications HTTP API under /api/v1/notifications (WP-023). No business logic here.

- the centre (`GET ""`, `GET /{id}`, `POST /read`): every signed-in user, their own entries only;
- preferences (`/preferences`): every signed-in user, their own; If-Match ("0" before the first
  save);
- rules (`/rules`) and the mail-waiting status (`/status`): `notifications.manage`; If-Match,
  audited;
- the delivery log of a record (`/deliveries`): whoever may see the record in full (staff).
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission, require_signed_in
from app.core.config import Settings
from app.core.database import TenantSession
from app.core.errors import PermissionDenied, ProblemDetail
from app.modules.audit import audited
from app.modules.identity_access import PolicyService, Subject, get_policy
from app.modules.notifications.domain.rules import ConditionOperator
from app.modules.notifications.infra.models import Notification
from app.modules.notifications.service import admin, centre
from app.modules.notifications.service.engine import waiting_count
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.ratelimit import rate_limit
from app.shared.mail import mail_configured
from app.shared.notifications.ports import NotificationCategory, NotificationChannel

Responses = dict[int | str, dict[str, object]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission."},
}
CONFLICT: Responses = {
    409: {"model": ProblemDetail, "description": "Stale If-Match: version_conflict."},
}
NOT_FOUND: Responses = {404: {"model": ProblemDetail, "description": "Not found or not yours."}}
FORBIDDEN: Responses = {
    403: {"model": ProblemDetail, "description": "Not staff (mail_status_staff_only)."}
}

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    dependencies=[Depends(rate_limit("notifications"))],
    responses=RESPONSES,
)

SignedIn = Annotated[Subject, Depends(require_signed_in())]
Policy = Annotated[PolicyService, Depends(get_policy)]
Manage = Annotated[Subject, Depends(require_permission(admin.MANAGE))]


def _app_settings(request: Request) -> Settings:
    # The app's own settings (tests pass theirs), never a fresh read of backend/.env.
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(_app_settings)]


# --- the centre ------------------------------------------------------------------------------


class NotificationOut(BaseModel):
    """One entry of your notification centre, in your language."""

    id: uuid.UUID
    event_code: str
    record_type: str
    record_id: uuid.UUID
    display_id: str
    title: str
    link: str = Field(description="Path in the console, e.g. /incidents/<id>.")
    urgent: bool
    read: bool
    created_at: datetime


class NotificationCentreOut(BaseModel):
    """A page of your entries, newest first, and the unread count."""

    items: list[NotificationOut]
    next_cursor: uuid.UUID | None
    unread: int


def _out(row: Notification) -> NotificationOut:
    return NotificationOut(
        id=row.id,
        event_code=row.event_code,
        record_type=row.record_type,
        record_id=row.record_id,
        display_id=row.display_id,
        title=row.title,
        link=row.link,
        urgent=row.urgent,
        read=row.read_at is not None,
        created_at=row.created_at,
    )


@router.get("", summary="Your notifications")
async def list_notifications(
    session: TenantSession,
    subject: SignedIn,
    *,
    cursor: Annotated[uuid.UUID | None, Query(description="next_cursor of the last page")] = None,
    limit: Annotated[int, Query(ge=1, le=centre.PAGE_MAX)] = 30,
    unread: Annotated[bool, Query(description="Only unread entries")] = False,
) -> NotificationCentreOut:
    """Your own entries only (whatever the request says)."""
    found = await centre.page(
        session, subject.user_id, cursor=cursor, limit=limit, unread_only=unread
    )
    return NotificationCentreOut(
        items=[_out(row) for row in found.items], next_cursor=found.next_cursor, unread=found.unread
    )


class NotificationReadIn(BaseModel):
    """Entries to mark read; leave `ids` out to mark every unread entry read."""

    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] | None = Field(default=None, max_length=centre.PAGE_MAX)


class NotificationReadOut(BaseModel):
    """How many changed, and the unread count after."""

    changed: int
    unread: int


@router.post("/read", summary="Mark notifications read")
async def mark_read(
    body: NotificationReadIn, session: TenantSession, subject: SignedIn
) -> NotificationReadOut:
    """Your other devices update at once (personal channel)."""
    changed = await centre.mark_read(session, subject.user_id, body.ids)
    return NotificationReadOut(
        changed=changed, unread=await centre.unread_count(session, subject.user_id)
    )


# --- preferences -----------------------------------------------------------------------------


class NotificationChoiceOut(BaseModel):
    """One category on one channel."""

    category: NotificationCategory
    channel: NotificationChannel
    on: bool
    locked: bool = Field(description="Required by your organization: cannot be switched off.")


class NotificationPreferencesOut(BaseModel):
    """Your notification preferences."""

    choices: list[NotificationChoiceOut]
    do_not_disturb: bool
    version: int


class NotificationChoiceIn(BaseModel):
    """A category switched off on a channel."""

    model_config = ConfigDict(extra="forbid")

    category: NotificationCategory
    channel: NotificationChannel


class NotificationPreferencesIn(BaseModel):
    """Everything switched off (the rest is on), and do-not-disturb."""

    model_config = ConfigDict(extra="forbid")

    off: list[NotificationChoiceIn] = Field(default_factory=list, max_length=50)
    do_not_disturb: bool = False


def _preferences_out(view: centre.PreferenceView) -> NotificationPreferencesOut:
    return NotificationPreferencesOut(
        choices=[
            NotificationChoiceOut(
                category=category,
                channel=channel,
                on=category.value in view.locked
                or (category.value, channel) not in view.preferences.off,
                locked=category.value in view.locked,
            )
            for category in NotificationCategory
            for channel in NotificationChannel
        ],
        do_not_disturb=view.preferences.do_not_disturb,
        version=view.version,
    )


@router.get("/preferences", summary="Your notification preferences")
async def get_preferences(
    session: TenantSession, subject: SignedIn, response: Response
) -> NotificationPreferencesOut:
    """Per category and channel; locked ones are required by your organization."""
    view = await centre.preferences(session, subject.user_id)
    set_etag(response, view.version)
    return _preferences_out(view)


@router.put("/preferences", summary="Change your notification preferences", responses=CONFLICT)
async def put_preferences(
    body: NotificationPreferencesIn,
    session: TenantSession,
    subject: SignedIn,
    version: ExpectedVersion,
    response: Response,
) -> NotificationPreferencesOut:
    """If-Match: the version you read ("0" before the first save)."""
    view = await centre.save_preferences(
        session,
        subject.user_id,
        expected_version=version,
        off=[(c.category.value, c.channel.value) for c in body.off],
        do_not_disturb=body.do_not_disturb,
    )
    set_etag(response, view.version)
    return _preferences_out(view)


# --- rules (admins) --------------------------------------------------------------------------


class NotificationCondition(BaseModel):
    """The record's `field` is (not) one of `values`."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(max_length=40)
    operator: ConditionOperator
    values: list[str] = Field(min_length=1, max_length=20)


class NotificationRuleIn(BaseModel):
    """An event's rule."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    recipients: list[str] = Field(default_factory=list, max_length=10)
    channels: list[NotificationChannel] = Field(default_factory=list, max_length=2)
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=admin.NAMED_MAX)
    group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=admin.NAMED_MAX)
    conditions: list[NotificationCondition] = Field(default_factory=list, max_length=20)
    notify_actor: bool = False


class NotificationRuleOut(BaseModel):
    """An event with the rule that applies to it now."""

    event_code: str
    record_type: str
    category: NotificationCategory
    required: bool = Field(description="People cannot switch it off in their preferences.")
    is_default: bool = Field(description="True while the shipped default applies.")
    enabled: bool
    recipients: list[str]
    channels: list[NotificationChannel]
    user_ids: list[uuid.UUID]
    group_ids: list[uuid.UUID]
    conditions: list[NotificationCondition]
    notify_actor: bool
    default_enabled: bool
    default_recipients: list[str]
    recipient_kinds: list[str] = Field(description="Relative recipients the record type offers.")
    condition_fields: list[str]
    version: int
    updated_at: datetime | None
    updated_by: uuid.UUID | None


def _rule_out(view: admin.RuleView) -> NotificationRuleOut:
    rule, event, source = view.rule, view.event, view.source
    return NotificationRuleOut(
        event_code=event.code,
        record_type=source.record_type,
        category=event.category,
        required=event.required,
        is_default=view.version == 0,
        enabled=rule.enabled,
        recipients=list(rule.recipients),
        channels=list(rule.channels),
        user_ids=list(rule.user_ids),
        group_ids=list(rule.group_ids),
        conditions=[
            NotificationCondition(field=c.field, operator=c.operator, values=list(c.values))
            for c in rule.conditions
        ],
        notify_actor=rule.notify_actor,
        default_enabled=event.default.enabled,
        default_recipients=list(event.default.recipients),
        recipient_kinds=list(source.recipient_kinds),
        condition_fields=list(source.conditions),
        version=view.version,
        updated_at=view.updated_at,
        updated_by=view.updated_by,
    )


@router.get("/rules", summary="Notification rules of every event")
async def list_rules(session: TenantSession, subject: Manage) -> list[NotificationRuleOut]:
    """Every event every module registered, with the rule that applies (no set-up step)."""
    del subject
    return [_rule_out(view) for view in await admin.rules(session)]


@router.put(
    "/rules/{event_code}",
    summary="Change an event's rule",
    responses=CONFLICT | NOT_FOUND,
    dependencies=[
        audited(
            "notification.rule_changed",
            object_type="notification_rule",
            detail_params=("event_code",),
        )
    ],
)
async def put_rule(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    event_code: str,
    body: NotificationRuleIn,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
) -> NotificationRuleOut:
    """If-Match: the version you read ("0" while the default applies)."""
    wanted = admin.parse_rule(
        enabled=body.enabled,
        recipients=body.recipients,
        channels=[c.value for c in body.channels],
        user_ids=body.user_ids,
        group_ids=body.group_ids,
        conditions=[c.model_dump() for c in body.conditions],
        notify_actor=body.notify_actor,
    )
    view = await admin.save_rule(session, subject, event_code, wanted, expected_version=version)
    set_etag(response, view.version)
    return _rule_out(view)


@router.delete(
    "/rules/{event_code}",
    summary="Reset an event's rule to the shipped default",
    responses=CONFLICT | NOT_FOUND,
    dependencies=[
        audited(
            "notification.rule_reset",
            object_type="notification_rule",
            detail_params=("event_code",),
        )
    ],
)
async def reset_rule(
    event_code: str, session: TenantSession, subject: Manage, version: ExpectedVersion
) -> NotificationRuleOut:
    """If-Match: the version of the saved rule."""
    return _rule_out(await admin.reset_rule(session, subject, event_code, expected_version=version))


class NotificationStatusOut(BaseModel):
    """For the admins' banner: e-mails waiting because outgoing mail is not set up."""

    mail_configured: bool
    waiting: int


@router.get("/status", summary="Notification delivery status")
async def status(
    session: TenantSession, subject: Manage, settings: AppSettings
) -> NotificationStatusOut:
    """How many e-mails wait for outgoing mail (REQ-NTF-020 AC3)."""
    del subject
    return NotificationStatusOut(
        mail_configured=mail_configured(settings), waiting=await waiting_count(session)
    )


# Who can set mail up: the people who manage mailboxes (integrations, Admin > Mail).
MAIL_ADMINS = "mailboxes.manage"
WHO_CAN_FIX_LIMIT = 10


class MailFixerOut(BaseModel):
    """A person by name only (no address: this is shown to every technician)."""

    id: uuid.UUID
    display_name: str


class MailStatusOut(BaseModel):
    """For the reply composer (REQ-INC-060): whether a reply can go out by e-mail now."""

    mail_configured: bool
    waiting: int = Field(description="E-mails waiting for outgoing mail in this organisation.")
    who_can_fix: list[MailFixerOut] = Field(description="People who can set mail up (names only).")


@router.get("/mail-status", summary="Whether replies can go out by e-mail", responses=FORBIDDEN)
async def mail_status(
    session: TenantSession, subject: SignedIn, settings: AppSettings, policy: Policy
) -> MailStatusOut:
    """For staff who reply on records (any `*.reply` permission); others get 403."""
    if not any(permission.endswith(".reply") for permission in subject.grants):
        raise PermissionDenied(code="mail_status_staff_only")
    fixers = await policy.holders(session, subject.tenant_id, MAIL_ADMINS, limit=WHO_CAN_FIX_LIMIT)
    return MailStatusOut(
        mail_configured=mail_configured(settings),
        waiting=await waiting_count(session),
        who_can_fix=[MailFixerOut(id=i, display_name=name) for i, name in fixers],
    )


# --- delivery log of a record ----------------------------------------------------------------


class NotificationDeliveryOut(BaseModel):
    """One notification of a record: to whom, how, when, and whether it went (REQ-INC-134)."""

    id: uuid.UUID
    event_code: str
    recipient_id: uuid.UUID | None
    recipient_name: str | None
    channel: NotificationChannel
    state: Literal["queued", "waiting", "sent", "failed", "suppressed"]
    reason: str | None = Field(description="Code; the UI shows its label.")
    created_at: datetime


@router.get("/deliveries", summary="Notifications of a record", responses=NOT_FOUND)
async def deliveries(
    session: TenantSession,
    subject: SignedIn,
    record_type: Annotated[str, Query(max_length=40)],
    record_id: uuid.UUID,
) -> list[NotificationDeliveryOut]:
    """Newest first (at most 200); for people who may see the record in full."""
    entries = await admin.delivery_log(session, subject, record_type, record_id)
    return [
        NotificationDeliveryOut(
            id=e.row.id,
            event_code=e.row.event_code,
            recipient_id=e.row.user_id,
            recipient_name=e.recipient_name,
            channel=NotificationChannel(e.row.channel),
            state=e.state,  # type: ignore[arg-type]  # mail and delivery states are both listed
            reason=e.reason,
            created_at=e.row.created_at,
        )
        for e in entries
    ]
