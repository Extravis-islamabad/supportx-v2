"""Mailboxes HTTP API under /api/v1/integrations/mailboxes (WP-024). No business logic here.

Everything needs `mailboxes.manage`. Passwords go in, never come out (`has_password` says whether
one is stored). Changes use If-Match and are audited; create takes an Idempotency-Key.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.config import Settings
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import audited
from app.modules.identity_access import Subject
from app.modules.integrations.domain.mailboxes import (
    AfterFetch,
    ConnectionSecurity,
    MailboxCreates,
    MailboxState,
    UnknownSenders,
)
from app.modules.integrations.infra.imap import ImapSettings
from app.modules.integrations.service import mailboxes as service
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

Responses = dict[int | str, dict[str, object]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission (mailboxes.manage)."},
    404: {"model": ProblemDetail, "description": "No such mailbox (mailbox_not_found)."},
}
CONFLICT: Responses = {409: {"model": ProblemDetail, "description": "Stale If-Match, or taken."}}

router = APIRouter(
    prefix="/integrations/mailboxes",
    tags=["integrations"],
    dependencies=[Depends(rate_limit("integrations"))],
    responses=RESPONSES,
)
Manage = Annotated[Subject, Depends(require_permission(service.MANAGE))]


def _app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(_app_settings)]


class MailboxFields(BaseModel):
    """A mailbox's settings (all optional when changing one)."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=120)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    security: ConnectionSecurity | None = None
    allow_plain: bool | None = Field(
        default=None, description="Allow a connection without TLS (audited)."
    )
    username: str | None = Field(default=None, min_length=1, max_length=320)
    folder: str | None = Field(default=None, min_length=1, max_length=255)
    after_fetch: AfterFetch | None = None
    move_to: str | None = Field(default=None, max_length=255)
    creates: MailboxCreates | None = None
    group_id: uuid.UUID | None = None
    unknown_senders: UnknownSenders | None = None
    allowed_domains: list[str] | None = Field(default=None, max_length=50)
    enabled: bool | None = None


class MailboxIn(MailboxFields):
    """A new mailbox."""

    address: str = Field(min_length=3, max_length=320)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=993, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=500, description="Stored sealed; never shown.")


class MailboxPatch(MailboxFields):
    """Fields to change; a password replaces the stored one."""

    password: str | None = Field(default=None, min_length=1, max_length=500)


class MailboxOut(BaseModel):
    """A mailbox as the mail page shows it."""

    id: uuid.UUID
    address: str
    display_name: str | None
    host: str
    port: int
    security: ConnectionSecurity
    allow_plain: bool
    username: str
    has_password: bool
    folder: str
    after_fetch: AfterFetch
    move_to: str | None
    creates: MailboxCreates
    group_id: uuid.UUID | None
    unknown_senders: UnknownSenders
    allowed_domains: list[str]
    enabled: bool
    state: MailboxState
    state_reason: str | None = Field(description="Code; the UI shows its label.")
    last_fetch_at: datetime | None
    held: int = Field(description="Messages kept for an admin (refused, flooding, not matched).")
    version: int

    @classmethod
    def of(cls, view: service.MailboxView) -> "MailboxOut":
        """From the service's view."""
        row = view.row
        return cls(
            id=row.id,
            address=row.address,
            display_name=row.display_name,
            host=row.host,
            port=row.port,
            security=ConnectionSecurity(row.security),
            allow_plain=row.allow_plain,
            username=row.username,
            has_password=view.has_password,
            folder=row.folder,
            after_fetch=AfterFetch(row.after_fetch),
            move_to=row.move_to,
            creates=MailboxCreates(row.creates),
            group_id=row.group_id,
            unknown_senders=UnknownSenders(row.unknown_senders),
            allowed_domains=list(row.allowed_domains),
            enabled=row.enabled,
            state=MailboxState(row.state),
            state_reason=row.state_reason,
            last_fetch_at=row.last_fetch_at,
            held=view.held,
            version=row.version,
        )


def _values(body: BaseModel, *, new: bool = False) -> dict[str, Any]:
    # A new mailbox keeps its defaults (port 993); a change carries only what was sent.
    if new:
        values = body.model_dump(exclude_none=True, exclude={"password"})
    else:
        values = body.model_dump(exclude_unset=True, exclude={"password"})
    return {k: (v.value if hasattr(v, "value") else v) for k, v in values.items()}


@router.get("", summary="Mailboxes")
async def list_mailboxes(session: TenantSession, subject: Manage) -> list[MailboxOut]:
    """Every mailbox with its state (the mail page, REQ-ADM-066 AC1)."""
    del subject
    return [MailboxOut.of(view) for view in await service.list_mailboxes(session)]


@router.post(
    "",
    summary="Add a mailbox",
    status_code=status.HTTP_201_CREATED,
    response_model=MailboxOut,
    responses=CONFLICT,
    dependencies=[audited("mailbox.created", object_type="mailbox")],
)
async def create_mailbox(
    body: MailboxIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    settings: AppSettings,
) -> Response:
    """Send an Idempotency-Key: a retried request returns the same 201."""

    async def run() -> Created:
        view = await service.create_mailbox(
            session, settings, subject.tenant_id, _values(body, new=True), password=body.password
        )
        out = MailboxOut.of(view)
        return Created(body=out, headers={"ETag": f'"{out.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/{mailbox_id}",
    summary="Change a mailbox",
    responses=CONFLICT,
    dependencies=[audited("mailbox.changed", object_type="mailbox", object_param="mailbox_id")],
)
async def update_mailbox(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    mailbox_id: uuid.UUID,
    body: MailboxPatch,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    settings: AppSettings,
) -> MailboxOut:
    """If-Match: the version you read. A connection change is tested again at the next fetch."""
    del subject
    view = await service.update_mailbox(
        session,
        settings,
        mailbox_id,
        _values(body),
        password=body.password,
        expected_version=version,
    )
    set_etag(response, view.row.version)
    return MailboxOut.of(view)


@router.delete(
    "/{mailbox_id}",
    summary="Remove a mailbox",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
    dependencies=[audited("mailbox.removed", object_type="mailbox", object_param="mailbox_id")],
)
async def remove_mailbox(
    mailbox_id: uuid.UUID, session: TenantSession, subject: Manage, version: ExpectedVersion
) -> Response:
    """Stop reading it; the records it made keep their history."""
    del subject
    await service.remove_mailbox(session, mailbox_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ConnectionTestIn(BaseModel):
    """Settings to try (a new password, or the stored one when left out)."""

    model_config = ConfigDict(extra="forbid")

    password: str | None = Field(default=None, max_length=500)


class ConnectionTestOut(BaseModel):
    """Whether the mailbox answered; `reason` is a code the UI shows as its label."""

    ok: bool
    reason: str | None = None


@router.post("/{mailbox_id}/test", summary="Test a mailbox's connection")
async def test_mailbox(
    mailbox_id: uuid.UUID,
    body: ConnectionTestIn,
    session: TenantSession,
    subject: Manage,
    settings: AppSettings,
) -> ConnectionTestOut:
    """Connects and looks for new mail; changes nothing on the server or here."""
    del subject
    row = (await service.get_mailbox(session, mailbox_id)).row
    password = body.password
    if password is None:
        from app.modules.integrations.service.fetching import (  # noqa: PLC0415 - one use
            SECRET_PURPOSE,
            key_ring,
        )

        ring = key_ring(settings)
        if ring is None or row.secret_key_id is None or row.secret_sealed is None:
            return ConnectionTestOut(ok=False, reason="mailbox_no_password")
        password = ring.unseal(
            row.tenant_id, SECRET_PURPOSE, row.secret_key_id, row.secret_sealed
        ).decode()
    reason = await service.test_connection(
        ImapSettings(
            host=row.host,
            port=row.port,
            security=ConnectionSecurity(row.security),
            username=row.username,
            password=password,
            folder=row.folder,
        )
    )
    return ConnectionTestOut(ok=reason is None, reason=reason)
