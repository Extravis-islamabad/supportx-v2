"""Dev-only quick sign-in for the showcase personas (D-151). Not part of the product API.

`/api/v1/auth/dev/...` answers 404, as if it did not exist, unless all of these hold:
- `SUPPORTX_DEV_QUICK_SIGN_IN` is on, which only the local dev profile allows (app/core/config.py)
  and the Helm chart refuses to render (templates/_guards.tpl);
- the request comes from a loopback address with a localhost Host header, and nothing forwarded
  from elsewhere;
- the showcase tenant exists.
A sign-in goes through Keycloak and the normal session path (AuthService.quick_sign_in) and is
audited (`session.quick_sign_in`: who, which persona, the client address). Hidden from OpenAPI.
"""

import uuid
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.core.authorization import public_route
from app.core.entitlements import entitlement_exempt
from app.core.errors import NotFound, ServiceUnavailable
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.audit import RequestFacts, record_alone
from app.modules.identity_access.bff.cookies import set_session_cookie
from app.modules.identity_access.bff.routes import Auth
from app.modules.identity_access.domain import quick_sign_in as quick
from app.modules.organization import tenant_for_slug

router = APIRouter(prefix="/auth/dev", tags=["dev"], include_in_schema=False)
log = get_logger(__name__)


async def _showcase(request: Request, auth: Auth) -> uuid.UUID:
    """The showcase tenant, when the dev-only setting is on and the request is local; else 404."""
    settings = auth.settings

    def present(names: tuple[str, ...]) -> list[str]:
        return [value for name in names if (value := request.headers.get(name)) is not None]

    client = request.client.host if request.client else None
    if not settings.dev_quick_sign_in or not quick.is_local(
        client,
        request.headers.get("host"),
        present(quick.FORWARDED_ADDRESS_HEADERS),
        present(quick.FORWARDED_HOST_HEADERS),
    ):
        raise NotFound
    database = getattr(request.app.state, "db", None)
    found = None if database is None else await tenant_for_slug(database, quick.SHOWCASE_SLUG)
    if found is None:
        raise NotFound
    return found.tenant_id


Showcase = Annotated[uuid.UUID, Depends(_showcase)]


class PersonaOut(BaseModel):
    """A button on the dev sign-in page (names come from labels: dev_persona.<code>)."""

    code: str
    email: str
    app: Literal["console", "portal"]
    enrolled: bool = Field(description="False: signs in the normal way and sets up two-step.")


class QuickSignInIn(BaseModel):
    """Which persona."""

    persona: str = Field(max_length=40)


class QuickSignInOut(BaseModel):
    """Where to go: the app, signed in; or the normal sign-in, for the new starter."""

    redirect_to: str


@router.get("/personas")
@entitlement_exempt
@public_route
async def personas(showcase: Showcase) -> list[PersonaOut]:
    """The showcase personas (dev only)."""
    del showcase
    return [
        PersonaOut(code=p.code, email=p.email, app=p.app, enrolled=p.enrolled)
        for p in quick.PERSONAS
    ]


@router.post("/sign-in")
@entitlement_exempt
@public_route
async def sign_in(
    body: QuickSignInIn, request: Request, response: Response, auth: Auth, showcase: Showcase
) -> QuickSignInOut:
    """Sign a persona in (dev only); the new starter goes to the normal sign-in instead."""
    # Another site open in the same browser could post here too (sign-in CSRF against
    # localhost): only the page on this local address may.
    origin = request.headers.get("origin")
    if origin is None or urlsplit(origin).netloc != request.headers.get("host"):
        raise NotFound
    who = quick.persona(body.persona)
    if who is None:
        raise NotFound
    if not who.enrolled:
        # The real flow, so QA tests setting up two-step sign-in: Keycloak's own pages.
        url = await auth.start_login(who.app, "/", None)
        return QuickSignInOut(redirect_to=url)
    database = getattr(request.app.state, "db", None)
    if database is None:  # no audit without a database: never a session either
        raise ServiceUnavailable(code="database_not_configured")
    result = await auth.quick_sign_in(who, showcase)
    try:
        await record_alone(
            database,
            TenantContext(showcase, uuid.UUID(result.session.user_id)),
            action_code="session.quick_sign_in",
            facts=RequestFacts.of(request, client=who.app),
            object_type="user",
            object_id=result.session.user_id,
            details={"persona": who.code},
        )
    except Exception as exc:
        # Every quick sign-in is audited (D-151): without its entry, no session (nor Keycloak's).
        log.exception("quick_sign_in_audit_failed", persona=who.code)
        await auth.logout(result.session_id, result.session)
        raise ServiceUnavailable from exc
    set_session_cookie(response, auth.settings, result.session_id)
    return QuickSignInOut(redirect_to=result.redirect_to)
