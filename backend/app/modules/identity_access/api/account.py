"""My account: the signed-in person's sign-in and security (WP-039 session 3, REQ-SEC-028).

`GET /account/security`: how the person signs in here (password, MFA and what their roles ask
of it, recovery codes) and their recent sign-ins (Keycloak's login events, kept 7 days). Any
signed-in person, for themselves only; no emailed code is ever needed to open it (AC1).

Changes go through Keycloak's own pages, started from here by the BFF's
`GET /auth/account-action` (bff/routes.py): changing the password asks for the current one first
(AC2); setting MFA up and new recovery codes are Keycloak's enrolment pages. Passwords never pass
through SupportX (D-099).
"""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.identity_access.domain.mfa import MFA_CREDENTIALS
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdmin,
    IdentityAdminNotConfigured,
    IdentityAdminUnavailable,
)
from app.modules.identity_access.infra.models import User
from app.modules.identity_access.service import mfa

router = APIRouter(prefix="/account", tags=["account"])
SignedIn = Annotated[Any, Depends(require_signed_in())]  # the module's Subject
RECENT_SIGN_INS = 10
SIGN_IN_EVENTS = [
    "LOGIN",
    "LOGIN_ERROR",
    "IDENTITY_PROVIDER_LOGIN",
    "IDENTITY_PROVIDER_LOGIN_ERROR",
]
WEEK_MS = 7 * 86400 * 1000


class SignInOut(BaseModel):
    """One recent sign-in to the installation (all of the person's organisations)."""

    at: datetime
    outcome: Literal["success", "failed"]
    method: Literal["password", "single_sign_on"]


class AccountSecurityOut(BaseModel):
    """How the person signs in, and their recent sign-ins."""

    has_password: bool = Field(description="False: they sign in through single sign-on only.")
    mfa_mode: Literal["off", "optional", "required"] = Field(
        description="What this organisation asks of the person (strictest of their roles)."
    )
    mfa_enrolled: bool
    mfa_due_at: datetime | None = Field(description="Required and not set up: set it up by then.")
    recovery_codes: bool = Field(description="They have recovery codes.")
    recent_sign_ins: list[SignInOut]
    details_available: bool = Field(
        description="False when the sign-in service could not be asked (shown, not an error)."
    )


def _admin(request: Request) -> IdentityAdmin | None:
    return getattr(request.app.state, "identity_admin", None)


@router.get("/security", summary="My sign-in and security")
async def my_security(
    request: Request, session: TenantSession, subject: SignedIn
) -> AccountSecurityOut:
    """The signed-in person's own sign-in methods and recent sign-ins."""
    status = await mfa.status_of(session, subject.user_id)
    person = await session.get(User, subject.user_id)
    found = AccountSecurityOut(
        has_password=True,
        mfa_mode=status.mode,
        mfa_enrolled=status.enrolled,
        mfa_due_at=status.due_at,
        recovery_codes=False,
        recent_sign_ins=[],
        details_available=False,
    )
    admin = _admin(request)
    if admin is None or person is None or person.external_subject is None:
        return found
    try:
        credentials = await admin.credentials(person.external_subject)
        since = int(datetime.now(UTC).timestamp() * 1000) - WEEK_MS
        events = await admin.login_events(SIGN_IN_EVENTS, since, person.external_subject)
    except (IdentityAdminUnavailable, IdentityAdminNotConfigured):
        return found
    types = {credential.type for credential in credentials}
    return found.model_copy(
        update={
            "has_password": "password" in types,
            "mfa_enrolled": "otp" in types,
            "recovery_codes": bool(types & (MFA_CREDENTIALS - {"otp"})),
            "recent_sign_ins": [
                SignInOut(
                    at=datetime.fromtimestamp(event.time_ms / 1000, UTC),
                    outcome="failed" if event.type.endswith("_ERROR") else "success",
                    method="single_sign_on" if "IDENTITY_PROVIDER" in event.type else "password",
                )
                for event in events[:RECENT_SIGN_INS]
            ],
            "details_available": True,
        }
    )
