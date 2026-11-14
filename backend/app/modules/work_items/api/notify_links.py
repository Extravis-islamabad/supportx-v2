"""Stopping mails to an address kept informed (WP-046a S6; REQ-INC-066), without sign-in.

    POST /api/v1/public/notify-links/peek   {token, tenant}   what the page shows before asking
    POST /api/v1/public/notify-links/stop   {token, tenant}   stop them, once

Lane B's conditions: the link in the mail opens a page that asks first (a GET does nothing, so a
mail scanner following links changes nothing); only its button posts. The token travels in the
body, never a URL a server logs. Unknown, used, expired and another tenant's tokens get one
answer (404 `notify_link_not_found`), the cost of a hash lookup. Both rate-limit budgets of the
shared public-link guard apply. The stop is audited with the record and the masked address.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from app.core.authorization import public_route
from app.core.database import Database, get_database
from app.core.entitlements import entitlement_exempt
from app.core.errors import NotFound
from app.core.tenancy import TenantContext
from app.modules.audit import AuditActorType, RequestFacts, record
from app.modules.organization import link_tenant
from app.modules.work_items.domain.kept_informed import masked
from app.modules.work_items.service import kept_informed
from app.shared.action_links.domain import TOKEN_LENGTH
from app.shared.api.public_links import PublicLinks, private_answers
from app.shared.api.ratelimit import ip_rate_limit

PER_ADDRESS = 60  # a minute, an outer cap before the guard's two budgets
public_router = APIRouter(
    prefix="/public/notify-links",
    tags=["work-items"],
    # Errors carry no-store and no-referrer too (lane B's note on #490), rate limits included.
    dependencies=[
        Depends(private_answers),
        Depends(ip_rate_limit("notify_links_public_address", PER_ADDRESS)),
    ],
)
GUARD = PublicLinks(
    group="notify_links_public", scope_name="notify-links-address", resolver=link_tenant
)
DatabaseDep = Annotated[Database, Depends(get_database)]
NO_REFERRER = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}


class NotifyTokenIn(BaseModel):
    """The token from the page's URL fragment, and the link's `?t=` slug."""

    # Any length up to a bound: a wrong one gets the same 404 as every refused token (lane B).
    token: str = Field(max_length=TOKEN_LENGTH * 4)
    tenant: str | None = Field(default=None, max_length=63)


class NotifyLinkOut(BaseModel):
    """What the page shows before asking: never the full address."""

    display_id: str
    address: str = Field(description="Masked, e.g. s***@acme.test.")


def _gone() -> NotFound:
    return NotFound(code="notify_link_not_found")


@public_router.post("/peek", summary="What a stop-these-mails link would do (no sign-in)")
@entitlement_exempt  # no session: the token is the credential, and stopping mail is never paid
@public_route  # no sign-in on purpose: the address belongs to no account
async def peek(
    payload: NotifyTokenIn, request: Request, response: Response, database: DatabaseDep
) -> NotifyLinkOut:
    """Never acts."""
    response.headers.update(NO_REFERRER)
    tenant_id = await GUARD.tenant(request, response, database, payload.tenant)
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        try:
            display_id, address = await kept_informed.peek(session, payload.token)
        except kept_informed.StopRefused:
            raise _gone() from None
    return NotifyLinkOut(display_id=display_id, address=address)


@public_router.post(
    "/stop",
    summary="Stop mails to an address kept informed (no sign-in)",
    status_code=status.HTTP_204_NO_CONTENT,
)
@entitlement_exempt  # no session: the token is the credential, and stopping mail is never paid
@public_route  # no sign-in on purpose: the address belongs to no account
async def stop(
    payload: NotifyTokenIn, request: Request, response: Response, database: DatabaseDep
) -> None:
    """Once: the address leaves the record's list, in one transaction with its audit entry."""
    response.headers.update(NO_REFERRER)
    tenant_id = await GUARD.tenant(request, response, database, payload.tenant)
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        try:
            link = await kept_informed.stop(session, payload.token)
        except kept_informed.StopRefused:
            raise _gone() from None
        await record(
            session,
            action_code="notify_link.used",
            facts=RequestFacts.of(request, client="portal"),
            object_type="work_item",
            object_id=link.work_item_id,
            # The address masked, never in clear (lane B); `via` names the public link.
            details={"address": masked(link.address), "via": "public_link"},
            actor=(AuditActorType.SYSTEM, None),
        )
