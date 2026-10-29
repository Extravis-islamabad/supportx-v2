"""Mailboxes HTTP API under /api/v1/integrations/mailboxes (WP-024). No business logic here.

Everything needs `mailboxes.manage`. Passwords go in, never come out (`has_password` says whether
one is stored). Changes use If-Match and are audited; create takes an Idempotency-Key.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.config import Settings
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import Subject
from app.modules.integrations.domain.mailboxes import (
    AfterFetch,
    AuthModel,
    ConnectionSecurity,
    CredentialKind,
    MailboxCreates,
    MailboxProtocol,
    MailboxState,
    UnknownSenders,
    needs_sign_in,
)
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

    auth_model: AuthModel | None = Field(
        default=None,
        description="Microsoft 365: app (no one signs in) or delegated. Gmail: delegated.",
    )
    client_id: str | None = Field(default=None, min_length=1, max_length=255)
    directory_id: str | None = Field(
        default=None, min_length=1, max_length=64, description="Microsoft Entra tenant ID."
    )
    credential_kind: CredentialKind | None = None
    credential_expires_at: datetime | None = Field(
        default=None,
        description="When the client secret expires (read from a certificate); warned ahead.",
    )
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


SECRET_MAX = 20_000  # a PEM certificate with its private key


class MailboxIn(MailboxFields):
    """A new mailbox: IMAP (server, account, password) or Microsoft 365 / Gmail (OAuth app)."""

    address: str = Field(min_length=3, max_length=320)
    protocol: MailboxProtocol = MailboxProtocol.IMAP
    port: int | None = Field(default=None, ge=1, le=65535, description="IMAP: 993 when left out.")
    password: str | None = Field(
        default=None, min_length=1, max_length=500, description="IMAP. Stored sealed; never shown."
    )
    client_secret: str | None = Field(
        default=None,
        min_length=1,
        max_length=SECRET_MAX,
        description="The OAuth app's secret, or its certificate and private key (PEM). Sealed.",
    )


class MailboxPatch(MailboxFields):
    """Fields to change; a password or client secret replaces the stored one."""

    password: str | None = Field(default=None, min_length=1, max_length=500)
    client_secret: str | None = Field(default=None, min_length=1, max_length=SECRET_MAX)


class MailboxOut(BaseModel):
    """A mailbox as the mail page shows it."""

    id: uuid.UUID
    address: str
    display_name: str | None
    protocol: MailboxProtocol
    host: str | None
    port: int | None
    security: ConnectionSecurity
    allow_plain: bool
    username: str | None
    has_password: bool = Field(description="A password or client secret is stored.")
    auth_model: AuthModel | None
    client_id: str | None
    directory_id: str | None
    credential_kind: CredentialKind | None
    credential_expires_at: datetime | None
    needs_sign_in: bool = Field(description="Someone must sign in as the mailbox (consent).")
    signed_in: bool = Field(description="A sign-in (refresh token) is stored.")
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
    flooding: bool = Field(
        description="A sender went over the flood limit; their mail waits in the review queue."
    )
    version: int

    @classmethod
    def of(cls, view: service.MailboxView) -> "MailboxOut":
        """From the service's view."""
        row = view.row
        return cls(
            id=row.id,
            address=row.address,
            display_name=row.display_name,
            protocol=MailboxProtocol(row.protocol),
            host=row.host,
            port=row.port,
            security=ConnectionSecurity(row.security),
            allow_plain=row.allow_plain,
            username=row.username,
            has_password=view.has_password,
            auth_model=AuthModel(row.auth_model) if row.auth_model else None,
            client_id=row.client_id,
            directory_id=row.directory_id,
            credential_kind=CredentialKind(row.credential_kind) if row.credential_kind else None,
            credential_expires_at=row.credential_expires_at,
            needs_sign_in=needs_sign_in(
                MailboxProtocol(row.protocol), AuthModel(row.auth_model) if row.auth_model else None
            ),
            signed_in=row.token_sealed is not None,
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
            flooding=view.flooding,
            version=row.version,
        )


SECRETS = {"password", "client_secret"}


def _values(body: BaseModel, *, new: bool = False) -> dict[str, Any]:
    # A new mailbox keeps its defaults (port 993); a change carries only what was sent.
    if new:
        values = body.model_dump(exclude_none=True, exclude=SECRETS)
        if values.get("protocol", "imap") == "imap":
            values.setdefault("port", 993)
    else:
        values = body.model_dump(exclude_unset=True, exclude=SECRETS)
    return {k: (v.value if hasattr(v, "value") else v) for k, v in values.items()}


def _secret(body: "MailboxIn | MailboxPatch | ConnectionTestIn") -> str | None:
    return body.password or body.client_secret


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
            session, settings, subject.tenant_id, _values(body, new=True), password=_secret(body)
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
        password=_secret(body),
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
    """A new password or client secret to try, or the stored one when left out."""

    model_config = ConfigDict(extra="forbid")

    password: str | None = Field(default=None, max_length=500)
    client_secret: str | None = Field(default=None, max_length=SECRET_MAX)


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
    reason = await service.try_connection(row, settings, secret=_secret(body))
    return ConnectionTestOut(ok=reason is None, reason=reason)


def origin_of(request: Request, settings: Settings) -> str:
    """The address the admin is on (a tenant's own address, WP-017), with the console's scheme.

    The session cookie is bound to this host, so the consent comes back to the same session.
    """
    console = urlsplit(settings.console_url)
    return f"{console.scheme}://{request.headers.get('host') or console.netloc}"


class MailboxSignInOut(BaseModel):
    """Where to send the browser: Microsoft's or Google's sign-in, for the mailbox's account."""

    authorize_url: str


@router.post(
    "/{mailbox_id}/sign-in",
    summary="Start signing in as the mailbox (consent)",
    responses=CONFLICT,
    dependencies=[
        audited("mailbox.consent_started", object_type="mailbox", object_param="mailbox_id")
    ],
)
async def start_sign_in(
    mailbox_id: uuid.UUID,
    request: Request,
    session: TenantSession,
    subject: Manage,
    settings: AppSettings,
) -> MailboxSignInOut:
    """Gmail, and Microsoft 365 with delegated permission. Valid ten minutes, for you only."""
    url = await service.start_sign_in(
        session,
        settings,
        mailbox_id,
        admin_id=subject.user_id,
        origin=origin_of(request, settings),
    )
    return MailboxSignInOut(authorize_url=url)


oauth_router = APIRouter(
    prefix="/integrations/oauth",
    tags=["integrations"],
    dependencies=[Depends(rate_limit("integrations"))],
)


@oauth_router.get(
    "/callback",
    summary="Microsoft or Google sends the admin back here",
    status_code=status.HTTP_303_SEE_OTHER,
    response_class=RedirectResponse,
)
async def sign_in_callback(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and the provider's query
    request: Request,
    session: TenantSession,
    subject: Manage,
    settings: AppSettings,
    note: Annotated[AuditNote, audited("mailbox.connected", object_type="mailbox")],
    state: Annotated[str, Query(max_length=200)] = "",
    code: Annotated[str | None, Query(max_length=4000)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
) -> RedirectResponse:
    """Stores the sign-in and returns to Admin > Mail, which shows the result.

    The authorization code and state are never logged (see app.core.logging's query redaction).
    """
    origin = origin_of(request, settings)
    result = await service.complete_sign_in(
        session,
        settings,
        state=state,
        code=code,
        declined=error is not None,
        admin_id=subject.user_id,
        origin=origin,
    )
    note.object_id = str(result.mailbox_id) if result.mailbox_id else None
    if result.reason is not None:
        note.details = {"refused": result.reason}
    query = {"sign_in": result.reason or "ok"}
    if result.mailbox_id is not None:
        query["mailbox"] = str(result.mailbox_id)
    base = urlsplit(settings.console_url).path.rstrip("/")
    return RedirectResponse(
        f"{origin}{base}/admin/mail?{urlencode(query)}", status_code=status.HTTP_303_SEE_OTHER
    )


class WaitingOut(BaseModel):
    """A message in the review queue (held, or too large to take in)."""

    message_id: str
    sender: str
    subject: str
    outcome: Literal["held", "too_large"]
    reason: str | None = Field(description="Code; the UI shows its label.")
    reason_params: dict[str, str]
    received_at: datetime
    releasable: bool = Field(description="Whether handing it in again can help.")

    @classmethod
    def of(cls, waiting: service.WaitingMail) -> "WaitingOut":
        """From the service's view."""
        row = waiting.row
        return cls(
            message_id=row.message_id,
            sender=row.sender,
            subject=row.subject,
            outcome="too_large" if row.outcome == "too_large" else "held",
            reason=row.reason,
            reason_params=dict(row.reason_params),
            received_at=row.created_at,
            releasable=waiting.releasable,
        )


class WaitingIn(BaseModel):
    """Which waiting message (by its Message-ID)."""

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=500)


class ReleasedOut(BaseModel):
    """What a released message became; `reason` when it waits again."""

    outcome: str
    reason: str | None
    reason_params: dict[str, str]


WAITING_RESPONSES: Responses = {
    409: {"model": ProblemDetail, "description": "Not waiting any more (mail_not_waiting)."}
}


@router.get("/{mailbox_id}/waiting", summary="Mail waiting for an admin")
async def waiting_mail(
    mailbox_id: uuid.UUID, session: TenantSession, subject: Manage
) -> list[WaitingOut]:
    """The review queue: held mail is never invisible (D-109 (9))."""
    del subject
    return [WaitingOut.of(w) for w in await service.waiting_mail(session, mailbox_id)]


@router.post(
    "/{mailbox_id}/waiting/release",
    summary="Hand a held message in again",
    responses=WAITING_RESPONSES,
    dependencies=[
        audited("mailbox.mail_released", object_type="mailbox", object_param="mailbox_id")
    ],
)
async def release_mail(
    mailbox_id: uuid.UUID,
    body: WaitingIn,
    session: TenantSession,
    subject: Manage,
    settings: AppSettings,
) -> ReleasedOut:
    """Without the flood check; held again, with the new reason, if it still cannot be taken in."""
    row = await service.release_mail(
        session, settings, mailbox_id, body.message_id, admin_id=subject.user_id
    )
    return ReleasedOut(
        outcome=row.outcome, reason=row.reason, reason_params=dict(row.reason_params)
    )


@router.post(
    "/{mailbox_id}/waiting/discard",
    summary="Discard a waiting message",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WAITING_RESPONSES,
    dependencies=[
        audited("mailbox.mail_discarded", object_type="mailbox", object_param="mailbox_id")
    ],
)
async def discard_mail(
    mailbox_id: uuid.UUID, body: WaitingIn, session: TenantSession, subject: Manage
) -> Response:
    """It stays in the ledger as discarded, without its copy."""
    await service.discard_mail(session, mailbox_id, body.message_id, admin_id=subject.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
