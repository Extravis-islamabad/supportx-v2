"""A copied invite link, the person's side (REQ-SEC-021; WP-057 S2b-2), without sign-in.

    POST /api/v1/public/invite-links/peek    {token, tenant}             the page's form, or 404
    POST /api/v1/public/invite-links/accept  {token, tenant, password}   set it, once

Lane B's conditions:
- the token is in the link's fragment, which the page reads and clears before anything else, and
  posts in the body: no URL a server or proxy logs ever holds it;
- the tenant comes from the address, else the link's `?t=` slug, through the shared public-link
  guard (#485) with both of its rate-limit budgets; an unknown tenant looks like a wrong token;
- every way a link does not work gets one answer (404 `invite_link_invalid`); a password policy
  error is told only once the token checked out;
- Keycloak sets the password and takes the set-password action off; nothing else of the account
  changes (never `emailVerified`) and nobody is signed in here: they sign in as usual next;
- `invitation.accepted` is audited with the person as actor, their address and browser;
- `no-store` and `no-referrer` on every answer; neither token nor password is ever logged.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from app.core.authorization import public_route
from app.core.database import Database, get_database
from app.core.entitlements import entitlement_exempt
from app.core.tenancy import TenantContext
from app.modules.audit import AuditActorType, RequestFacts, record
from app.modules.identity_access.domain.password_policy import MAX_LENGTH
from app.modules.identity_access.infra.keycloak_admin import IdentityAdmin
from app.modules.identity_access.service import invitations
from app.modules.organization import link_tenant
from app.shared.api.public_links import PublicLinks, private_answers
from app.shared.api.ratelimit import ip_rate_limit

PER_ADDRESS = 20  # a minute, an outer cap before the guard's two budgets
public_router = APIRouter(
    prefix="/public/invite-links",
    tags=["identity"],
    # Errors carry no-store and no-referrer too (lane B's note on #490), rate limits included.
    dependencies=[
        Depends(private_answers),
        Depends(ip_rate_limit("invite_links_public_address", PER_ADDRESS)),
    ],
)
GUARD = PublicLinks(
    group="invite_links_public", scope_name="invite-links-address", resolver=link_tenant
)
DatabaseDep = Annotated[Database, Depends(get_database)]
PRIVATE = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}


class InviteTokenIn(BaseModel):
    """The token from the page's URL fragment, and the link's `?t=` slug."""

    # Any length up to a bound: a wrong one gets the same 404 as every refused token (lane B).
    token: str = Field(max_length=256)
    tenant: str | None = Field(default=None, max_length=63)


class InviteAcceptIn(InviteTokenIn):
    """The new password, checked by Keycloak against the realm's policy."""

    # Generous here so that "too long" is told only after the token checked out (lane B).
    password: str = Field(min_length=1, max_length=MAX_LENGTH * 8, repr=False)


class PasswordRulesOut(BaseModel):
    """What the form says a password needs (the installation's policy)."""

    min_length: int
    upper: bool
    lower: bool
    digits: bool
    special: bool


class InviteLinkPeekOut(BaseModel):
    """What the set-password page needs: which app to sign in to next, and the rules."""

    app: Literal["console", "portal"]
    rules: PasswordRulesOut


def _admin(request: Request) -> IdentityAdmin | None:
    return getattr(request.app.state, "identity_admin", None)


@public_router.post("/peek", summary="Whether an invite link works (no sign-in)")
@entitlement_exempt  # no session: the token is the credential, and joining is never paid
@public_route  # no sign-in on purpose: the person has no password yet
async def peek(
    payload: InviteTokenIn, request: Request, response: Response, database: DatabaseDep
) -> InviteLinkPeekOut:
    """Never changes anything."""
    response.headers.update(PRIVATE)
    tenant_id = await GUARD.tenant(request, response, database, payload.tenant)
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        found = await invitations.peek_link(
            session, _admin(request), payload.token, datetime.now(UTC)
        )
    rules = found.policy
    return InviteLinkPeekOut(
        app="console" if found.for_console else "portal",
        rules=PasswordRulesOut(
            min_length=rules.min_length,
            upper=rules.upper,
            lower=rules.lower,
            digits=rules.digits,
            special=rules.special,
        ),
    )


@public_router.post(
    "/accept",
    summary="Set a first password from an invite link (no sign-in)",
    status_code=status.HTTP_204_NO_CONTENT,
)
@entitlement_exempt  # no session: the token is the credential, and joining is never paid
@public_route  # no sign-in on purpose: the person has no password yet
async def accept(
    payload: InviteAcceptIn, request: Request, response: Response, database: DatabaseDep
) -> None:
    """Once: the password is set, the invitation accepted and audited in one transaction."""
    response.headers.update(PRIVATE)
    tenant_id = await GUARD.tenant(request, response, database, payload.tenant)
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        person = await invitations.accept_link(
            session, _admin(request), payload.token, payload.password, datetime.now(UTC)
        )
        await record(
            session,
            action_code="invitation.accepted",
            facts=RequestFacts.of(request),
            object_type="user",
            object_id=person,
            details={"via": "copied_link"},
            actor=(AuditActorType.PERSON, person),
        )
