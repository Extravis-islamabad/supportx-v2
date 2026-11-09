"""Signed one-time action links over HTTP (WP-030 s3; REQ-NTF-024; app/shared/action_links).

    POST /api/v1/action-links/peek          {token}       signed in: what the link would do
    POST /api/v1/action-links/use           {token, …}    signed in: take its action once
    POST /api/v1/public/action-links/peek   {token}       no sign-in (D-132, the default)
    POST /api/v1/public/action-links/use    {token, …}    no sign-in: as the link's recipient

All are POSTs with the token in the body: it never sits in a URL the server logs, and the
link's page reads it from the URL fragment (lane B's conditions 1 and 3); all are rate-limited
(condition 4). Without sign-in the token stands for its recipient (D-132): the tenant comes from
the address used, and the action runs in a session opened as the recipient, so their
permissions, audit entry and history apply; a tenant that wants a signed-in approver gets 403
`action_link_sign_in_required` there and the page asks the person to sign in.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

import valkey.exceptions
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.core.authorization import public_route, require_signed_in
from app.core.database import Database, TenantSession, get_database
from app.core.entitlements import ENTITLEMENT_GATE_STATE, EntitlementGate, entitlement_exempt
from app.core.errors import AppError, RateLimited, ValidationFailed
from app.core.tenancy import TenantContext
from app.modules.audit import (
    AuditActorType,
    AuditNote,
    AuditOutcome,
    RequestFacts,
    audited,
    record,
    record_alone,
)
from app.modules.identity_access import Subject, subject_for
from app.modules.organization import tenant_for_host, tenant_for_slug
from app.shared import action_links
from app.shared.action_links.domain import TOKEN_LENGTH
from app.shared.api.ratelimit import RATE_LIMITER_STATE, RateLimiter, rate_limit

router = APIRouter(
    prefix="/action-links",
    tags=["action-links"],
    dependencies=[Depends(rate_limit("action_links"))],
)
SignedIn = Annotated[Subject, Depends(require_signed_in())]
NO_REFERRER = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}


class TokenIn(BaseModel):
    """The link's token, from the page's URL fragment."""

    token: str = Field(min_length=TOKEN_LENGTH, max_length=TOKEN_LENGTH)
    tenant: str | None = Field(
        default=None,
        max_length=63,
        description=(
            "The link's `?t=`: the tenant's slug, for an address that names no tenant. "
            "Where the address names one, it wins and a different slug is refused."
        ),
    )


class UseIn(TokenIn):
    """The token, and what the action takes (e.g. a decision and its comment)."""

    body: dict[str, Any] = Field(default_factory=dict)


class OpenedOut(BaseModel):
    """What the link does, on what, until when, and what its page may show."""

    action: str
    object_type: str
    object_id: uuid.UUID
    expires_at: datetime
    summary: dict[str, Any]


@router.post("/peek", summary="What an action link would do")
async def peek(
    payload: TokenIn, session: TenantSession, subject: SignedIn, response: Response
) -> OpenedOut:
    """Never acts. 404 for an unknown link, 403 for someone else's, 409 used/expired/revoked."""
    response.headers.update(NO_REFERRER)
    opened = await action_links.peek(session, payload.token, subject)
    return OpenedOut(
        action=opened.action,
        object_type=opened.object_type,
        object_id=opened.object_id,
        expires_at=opened.expires_at,
        summary=dict(opened.summary),
    )


@router.post("/use", summary="Take an action link's action")
async def use(
    payload: UseIn,
    session: TenantSession,
    subject: SignedIn,
    response: Response,
    note: Annotated[AuditNote, audited("action_link.used", object_type="action_link")],
) -> dict[str, Any]:
    """Once: the link is marked used in the same transaction as the action."""
    response.headers.update(NO_REFERRER)
    opened, result = await action_links.use(session, payload.token, subject, payload.body)
    note.object_type = opened.object_type
    note.object_id = str(opened.object_id)
    note.details = {"action": opened.action}
    return dict(result)


# --- without sign-in (D-132, the default) -------------------------------------------------------

public_router = APIRouter(prefix="/public/action-links", tags=["action-links"])
DatabaseDep = Annotated[Database, Depends(get_database)]
PUBLIC_GROUP = "action_links_public"


# Where the address and the slug name no tenant, the token is looked up here: no tenant has this
# id, so row-level security finds nothing and the answer is the wrong token's, at its cost
# (lane B's review: an unknown tenant must look like a wrong token).
NO_TENANT = uuid.UUID(int=0)


async def _public_tenant(
    request: Request, response: Response, database: Database, slug: str | None
) -> uuid.UUID:
    """Where the token is looked up: the address's tenant, else the link's `?t=` slug.

    The address (subdomain or verified domain) wins; a slug naming another tenant is refused.
    Without tenant subdomains (on-prem, k3s) the address names none and the slug does. It only
    decides where the token is looked up: the token is the secret, and a token used on another
    tenant's address is simply not found there. Every way of not finding a tenant gives
    `NO_TENANT`, so the answer and its cost are a wrong token's.
    """
    slug = slug or None  # an empty `?t=` is no slug (lane B)
    # Two limits (lane B's review). Before any lookup, both budgets keyed on the client address
    # alone: a sweep over slugs or tenants' addresses shares one budget, and no client fills
    # another's. After it, the resolved tenant's own budget, as before ?t=: junk with unknown
    # slugs only ever fills NO_TENANT's, which no real link uses. Every request makes both hits.
    await _public_limit(request, response, _address_scope(request))
    tenant_id = await _resolve(request, database, slug)
    await _public_limit(request, response, tenant_id)
    return tenant_id


def _address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _address_scope(request: Request) -> uuid.UUID:
    """A budget scope of the client address alone, never shared with a tenant or another client."""
    return uuid.uuid5(NO_TENANT, f"action-links-address:{_address(request)}")


async def _resolve(request: Request, database: Database, slug: str | None) -> uuid.UUID:
    found = await tenant_for_host(
        database, request.headers.get("host"), request.app.state.settings.tenant_base_domain
    )
    if found is not None:
        return found.tenant_id if slug is None or slug == found.slug else NO_TENANT
    if slug is None:
        return NO_TENANT
    by_slug = await tenant_for_slug(database, slug)  # a bad pattern: None, before any query
    return by_slug.tenant_id if by_slug is not None else NO_TENANT


async def _public_limit(request: Request, response: Response, tenant_id: uuid.UUID) -> None:
    """Rate limit by client address: there is no person to key on (lane B)."""
    limiter: RateLimiter | None = getattr(request.app.state, RATE_LIMITER_STATE, None)
    if limiter is None:
        return
    try:
        decision = await limiter.hit(PUBLIC_GROUP, tenant_id, f"address:{_address(request)}")
    except (valkey.exceptions.ValkeyError, OSError):
        return  # the limiter is down: the token stays the protection
    if not decision.allowed:
        raise RateLimited(
            params={"retry_after_seconds": decision.reset_seconds}, headers=decision.headers()
        )
    response.headers.update(decision.headers())


async def _recipient(
    request: Request, database: Database, tenant_id: uuid.UUID, token: str, *, write: bool
) -> uuid.UUID:
    """The link's recipient, after the entitlement gate for its action's feature.

    For a write the gate also refuses read-only mode, as the action's own router would.
    """
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        recipient, feature = await action_links.recipient_of(session, token)
        gate: EntitlementGate | None = getattr(request.app.state, ENTITLEMENT_GATE_STATE, None)
        if gate is not None:
            await gate.check_request(
                TenantContext(tenant_id, user_id=recipient),
                feature=feature,
                write=write,
                session=session,
            )
    return recipient


@public_router.post("/peek", summary="What an e-mailed link would do (no sign-in)")
@entitlement_exempt  # no session: _recipient asks the gate for the action's own feature
@public_route  # no sign-in on purpose (D-132): the token is the credential
async def public_peek(
    payload: TokenIn, request: Request, response: Response, database: DatabaseDep
) -> OpenedOut:
    """Never acts (D-132: mail scanners open links).

    403 `action_link_sign_in_required` when the tenant wants a signed-in approver: the page
    then asks the person to sign in.
    """
    response.headers.update(NO_REFERRER)
    tenant_id = await _public_tenant(request, response, database, payload.tenant)
    recipient = await _recipient(request, database, tenant_id, payload.token, write=False)
    async with database.tenant_session(TenantContext(tenant_id, user_id=recipient)) as session:
        subject = await subject_for(session, tenant_id, recipient)
        opened = await action_links.peek(session, payload.token, subject)
    return OpenedOut(
        action=opened.action,
        object_type=opened.object_type,
        object_id=opened.object_id,
        expires_at=opened.expires_at,
        summary=dict(opened.summary),
    )


@public_router.post("/use", summary="Take an e-mailed link's action (no sign-in)")
@entitlement_exempt  # no session: _recipient asks the gate for the action's own feature
@public_route  # no sign-in on purpose (D-132): the token is the credential
async def public_use(
    payload: UseIn, request: Request, response: Response, database: DatabaseDep
) -> dict[str, Any]:
    """Once, as the link's recipient: their permissions, their audit entry and history.

    A refusal is audited too (as the recipient when known) and counts toward the link's cap of
    failed uses; never the token or its hash in the entry.
    """
    response.headers.update(NO_REFERRER)
    tenant_id = await _public_tenant(request, response, database, payload.tenant)
    facts = RequestFacts.of(request, client="portal")
    recipient: uuid.UUID | None = None
    try:
        recipient = await _recipient(request, database, tenant_id, payload.token, write=True)
        context = TenantContext(tenant_id, user_id=recipient)
        async with database.tenant_session(context) as session:
            subject = await subject_for(session, tenant_id, recipient)
            opened, result = await action_links.use(session, payload.token, subject, payload.body)
            await record(
                session,
                action_code="action_link.used",
                facts=facts,
                object_type=opened.object_type,
                object_id=opened.object_id,
                details={"action": opened.action, "signed_in": False},
                actor=(AuditActorType.PERSON, recipient),
            )
    except AppError as refused:
        if tenant_id == NO_TENANT:
            # No tenant to audit in and no link to count the failure on. Accepted (lane B's
            # review, minor 1): this answer skips the audit write a wrong token in a real tenant
            # makes, one transaction measurable over many tries. Peek, the obvious probe, has no
            # such difference, and slugs are no secret (every SaaS tenant's subdomain).
            raise
        await record_alone(
            database,
            TenantContext(tenant_id, user_id=recipient),
            action_code="action_link.used",
            facts=facts,
            outcome=AuditOutcome.REFUSED,
            reason_code=refused.instance_code,
            details={"signed_in": False},
            actor=(AuditActorType.PERSON, recipient)
            if recipient
            else (AuditActorType.SYSTEM, None),
        )
        if not isinstance(refused, ValidationFailed):  # a missing reason is not a probe
            async with database.tenant_session(TenantContext(tenant_id)) as session:
                await action_links.note_failed_use(session, payload.token)
        raise
    return dict(result)


__all__ = ["public_router", "router"]
