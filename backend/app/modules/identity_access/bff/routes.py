"""BFF endpoints under /api/v1/auth (D-009). Tokens never leave the server."""

import uuid
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.core.entitlements import entitlement_exempt
from app.core.errors import ServiceUnavailable, Unauthenticated
from app.modules.identity_access.bff.cookies import clear_session_cookie, set_session_cookie
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.domain.session import Session
from app.modules.identity_access.service.auth import AuthService, LoginFailure

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth(request: Request) -> AuthService:
    """The process AuthService; 503 `auth_not_configured` when login is not set up."""
    service: AuthService | None = getattr(request.app.state, "auth", None)
    if service is None:
        raise ServiceUnavailable(code="auth_not_configured")
    return service


Auth = Annotated[AuthService, Depends(get_auth)]


async def current_session(request: Request, auth: Auth) -> tuple[str, Session]:
    """The request's valid session (CSRF-checked for state-changing methods) or 401."""
    found = await auth.session_for(request)
    if found is None:
        raise Unauthenticated
    return found


CurrentSession = Annotated[tuple[str, Session], Depends(current_session)]


class UserOut(BaseModel):
    """The logged-in user (in the active tenant)."""

    id: uuid.UUID
    email: str
    display_name: str
    locale: Literal["en", "ar", "ur"]
    user_type: UserType
    roles: list[str]


class TenantOut(BaseModel):
    """A tenant the user belongs to."""

    id: uuid.UUID
    name: str


class MeResponse(BaseModel):
    """Session summary for the UI.

    `csrf_token` must be sent as X-CSRF-Token on every POST/PUT/PATCH/DELETE; it is tied to this
    session and changes when the session does.
    """

    user: UserOut
    tenant: TenantOut
    tenants: list[TenantOut]
    csrf_token: str


class SwitchTenantRequest(BaseModel):
    """Which of the user's tenants to make active."""

    tenant_id: uuid.UUID


@router.get(
    "/login",
    summary="Start login",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
)
@entitlement_exempt
async def login(
    auth: Auth,
    app: Annotated[Literal["console", "portal"], Query()] = "console",
    return_to: Annotated[str | None, Query(alias="returnTo", max_length=2048)] = None,
) -> RedirectResponse:
    """Redirect the browser to Keycloak (authorization code + PKCE, state, nonce).

    `returnTo` must be a same-origin relative path; anything else lands on `/`.
    """
    url = await auth.start_login(app, return_to)
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get(
    "/callback",
    summary="Finish login",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
)
@entitlement_exempt
async def callback(
    request: Request,
    auth: Auth,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Keycloak sends the browser here. Creates a new session and sets the session cookie.

    Failures are RFC 9457 problems for API clients. A browser navigation (Accept: text/html) is
    sent back to its app with `?auth_error=<code>` instead, which the app shows as a translated
    message (CLAUDE.md rule d: no raw codes or JSON on screen).
    """
    try:
        result = await auth.complete_login(
            code=code,
            state=state,
            error=error,
            previous_session_id=request.cookies.get(auth.cookie_name),
        )
    except LoginFailure as failure:
        if "text/html" not in request.headers.get("accept", ""):
            raise failure.problem from failure
        query = urlencode({"auth_error": failure.problem.instance_code})
        target = f"{auth.base_url(failure.app)}/?{query}"
        return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    response = RedirectResponse(result.redirect_to, status_code=status.HTTP_302_FOUND)
    set_session_cookie(response, auth.settings, result.session_id)
    return response


@router.get("/me", summary="Current session")
@entitlement_exempt
async def me(found: CurrentSession) -> MeResponse:
    """The logged-in user, active tenant, switchable tenants and CSRF token."""
    _session_id, session = found
    return MeResponse.model_validate(AuthService.describe(session))


@router.post("/logout", summary="Log out", status_code=status.HTTP_204_NO_CONTENT)
@entitlement_exempt
async def logout(found: CurrentSession, auth: Auth) -> Response:
    """End this session and the Keycloak session; clears the cookie."""
    session_id, session = found
    await auth.logout(session_id, session)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, auth.settings)
    return response


@router.post("/switch-tenant", summary="Switch active tenant")
@entitlement_exempt
async def switch_tenant(
    body: SwitchTenantRequest, found: CurrentSession, auth: Auth, response: Response
) -> MeResponse:
    """Make another of the user's tenants active. Issues a new session ID and CSRF token."""
    session_id, session = found
    new_id, switched = await auth.switch_tenant(session_id, session, body.tenant_id)
    set_session_cookie(response, auth.settings, new_id)
    return MeResponse.model_validate(AuthService.describe(switched))
