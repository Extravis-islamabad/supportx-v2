"""Confirm identity again for sensitive actions (REQ-SEC-027; WP-057 S2a).

A sensitive route declares `dependencies=[RecentAuth]` and is listed in RECENT_AUTH_ROUTES (a
guard test checks both ways, lane B's condition A2). A route sensitive for only some changes
calls `require_recent_auth` itself and is listed in CONDITIONAL_RECENT_AUTH. The caller passes
when they are signed in through a browser or app session (never an API key, never the mobile
app, which cannot confirm) and proved who they are within RECENT_AUTH_WINDOW. Otherwise 403 with
a labelled code: `reauth_required` (the console confirms in a pop-up, then retries once) or
`interactive_session_required`.

The facts come from the session layer (identity_access's resolver), which records them on the
request: `auth_time` is set only at sign-in and at a confirmation, from the verified, nonce-bound
ID token, never from a refresh's token (lane B's condition A1).
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import Depends, Request

from app.core.errors import PermissionDenied

RECENT_AUTH_WINDOW = timedelta(minutes=10)
RECENT_AUTH_STATE = "recent_auth"
REAUTH_REQUIRED = "reauth_required"
INTERACTIVE_SESSION_REQUIRED = "interactive_session_required"
API_KEY_NOT_ALLOWED = "api_key_not_allowed"

# Every route that asks for a recent confirmation, as "METHOD /api/v1/path". One list (lane B):
# tests/test_recent_auth_routes.py checks each carries RecentAuth and nothing else does.
RECENT_AUTH_ROUTES: tuple[str, ...] = (
    # Sign-in and security settings.
    "PUT /api/v1/identity/settings",
    "POST /api/v1/identity/settings/password-policy/apply",
    "PUT /api/v1/identity/sso-policy",
    "PUT /api/v1/identity/network-rules",
    "PUT /api/v1/identity/mfa/roles/{role_id}",
    "PUT /api/v1/identity/break-glass/{user_id}",
    "POST /api/v1/identity/sso",
    "PUT /api/v1/identity/sso/{provider_id}",
    "DELETE /api/v1/identity/sso/{provider_id}",
    "POST /api/v1/identity/sso/{provider_id}/switch-on",
    "POST /api/v1/identity/sso/{provider_id}/switch-off",
    "POST /api/v1/identity/people/{user_id}/reset-mfa",
    # Who may do what: roles, their permissions and who holds them.
    "POST /api/v1/roles",
    "PATCH /api/v1/roles/{role_id}",
    "PUT /api/v1/users/{user_id}/roles/{role_id}",
    "PUT /api/v1/roles/{role_id}/groups/{group_id}",
    "PUT /api/v1/automation/workflows/{workflow_id}/run-as/roles/{role_id}",
    # GDPR (D-171, ADR-052): legal hold, and both people of a person's erasure.
    "PUT /api/v1/people/{user_id}/legal-hold",
    "POST /api/v1/people/{user_id}/legal-hold/lift",
    "POST /api/v1/people/{user_id}/erasure",
    "POST /api/v1/erasures/{erasure_id}/approve",
    # Keys, exports and secret-bearing connections.
    "POST /api/v1/api-keys",
    "POST /api/v1/audit/exports",
    "POST /api/v1/integrations/directories",
    "PUT /api/v1/integrations/directories/{directory_id}",
    "DELETE /api/v1/integrations/directories/{directory_id}",
    "POST /api/v1/integrations/ldap-directories",
    "PUT /api/v1/integrations/ldap-directories/{directory_id}",
    "DELETE /api/v1/integrations/ldap-directories/{directory_id}",
    "POST /api/v1/integrations/mailboxes",
    "PATCH /api/v1/integrations/mailboxes/{mailbox_id}",
    "PUT /api/v1/integrations/connector-settings",
)

# Routes that ask only for some changes, so they call `require_recent_auth` in the endpoint
# instead of declaring RecentAuth: route → which change. The guard test checks each one calls it.
CONDITIONAL_RECENT_AUTH: dict[str, str] = {
    # A person's sign-in address is also where password resets go: changing it in a hijacked
    # admin session would hand over the account (lane B, #479). Other person fields stay open.
    "PATCH /api/v1/users/{user_id}/person": "a different sign-in e-mail",
}


@dataclass(frozen=True)
class SignInFreshness:
    """What the session layer knows about the caller, for RecentAuth."""

    interactive: bool  # a browser session (not an API key, not the mobile app)
    recent: bool  # proved who they are within RECENT_AUTH_WINDOW
    api_key: bool = False  # an API key's call: refused as the authorization layer refuses keys


def record_freshness(request: Request, facts: SignInFreshness) -> None:
    """Called by the session resolver for every signed-in request."""
    setattr(request.state, RECENT_AUTH_STATE, facts)


async def require_recent_auth(request: Request) -> None:
    """403 unless the caller confirmed who they are recently, in an interactive session."""
    facts: SignInFreshness | None = getattr(request.state, RECENT_AUTH_STATE, None)
    if facts is not None and facts.api_key:
        # The same answer the authorization layer gives a key on a route keys may not use.
        raise PermissionDenied(code=API_KEY_NOT_ALLOWED)
    if facts is None or not facts.interactive:
        raise PermissionDenied(code=INTERACTIVE_SESSION_REQUIRED)
    if not facts.recent:
        minutes = int(RECENT_AUTH_WINDOW.total_seconds() // 60)
        raise PermissionDenied(code=REAUTH_REQUIRED, params={"max_age_minutes": minutes})


RecentAuth: Any = Depends(require_recent_auth)  # Any: FastAPI's Depends() marker
