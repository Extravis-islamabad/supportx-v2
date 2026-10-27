"""The test sign-in of a single sign-on set-up (WP-039; REQ-SEC-007, REQ-SEC-008; D-094).

Before a set-up is switched on, an admin signs in through it once, in a pop-up:

1. `start`: a one-time login state marked as a test, and Keycloak's sign-in URL going straight
   to the set-up's provider (`kc_idp_hint`), for the tenant's organization, always asking for
   the password (`prompt=login`).
2. The callback (`finish`): the code is exchanged and the ID token verified as for any sign-in,
   but **no SupportX session and no person are created**. The result says whether the person
   arrived as a member of this tenant (their email in one of its domains) and what the provider
   sent for department and site. The tested person's Keycloak session is ended at once. Keycloak
   itself made them a member of the tenant's organization on this first sign-in: they are now a
   person the tenant may let in, which is what switching on will do anyway.
3. `result`: what the admin's screen polls. Still pending after the provider answered with an
   error: Keycloak showed its own error page and records only that the identity provider's
   answer could not be used (no reason, no provider name, proved on 26.8.1). A login error
   event since the test began is reported as that plain reason (REQ-SEC-007 AC1).

The record lives 15 minutes in Valkey, encrypted (it names the person).
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from app.core.errors import NotFound
from app.modules.identity_access.domain.identity import ClaimsError, identity_from, validate_claims
from app.modules.identity_access.domain.sso import DEPARTMENT_ATTRIBUTE, SITE_ATTRIBUTE
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdminNotConfigured,
    IdentityAdminUnavailable,
)
from app.modules.identity_access.infra.oidc import InvalidTokenError, PkcePair, TokenRejectedError

if TYPE_CHECKING:
    from app.modules.identity_access.service.auth import AuthService

TEST_TTL = timedelta(minutes=15)
LOGIN_ERRORS = [
    "IDENTITY_PROVIDER_LOGIN_ERROR",
    "IDENTITY_PROVIDER_FIRST_LOGIN_ERROR",
    "IDENTITY_PROVIDER_POST_LOGIN_ERROR",
]
DONE_PATH = "/sso-test-done"


@dataclass(frozen=True)
class TestStarted:
    """Where the pop-up goes, and the ID to ask for the result with."""

    test_id: str
    url: str


@dataclass(frozen=True)
class TestFinished:
    """The callback's outcome: where to send the pop-up, and what to audit."""

    redirect_to: str
    tenant_id: uuid.UUID
    admin_user_id: uuid.UUID
    provider_id: uuid.UUID
    passed: bool


async def start(  # noqa: PLR0913 - who, where and which set-up, keyword-only
    auth: "AuthService",
    *,
    tenant_id: uuid.UUID,
    slug: str,
    admin_user_id: uuid.UUID,
    provider_id: uuid.UUID,
    alias: str,
) -> TestStarted:
    """Begin a test sign-in through `alias` for the tenant."""
    test_id, state, nonce = (secrets.token_urlsafe(24) for _ in range(3))
    pkce = PkcePair.generate()
    now_ms = int(auth.clock.now().timestamp() * 1000)
    await auth.store.put_sso_test(
        test_id,
        {
            "status": "pending",
            "tenant_id": str(tenant_id),
            "provider_id": str(provider_id),
            "started_ms": now_ms,
        },
        TEST_TTL,
    )
    await auth.store.put_login(
        state,
        {
            "app": "console",
            "nonce": nonce,
            "verifier": pkce.verifier,
            "return_to": "/",
            "origin": None,
            "organization": slug,
            "test": {
                "id": test_id,
                "tenant_id": str(tenant_id),
                "admin_user_id": str(admin_user_id),
                "provider_id": str(provider_id),
            },
        },
        TEST_TTL,
    )
    url = await auth.oidc.authorization_url(
        auth.client("console"),
        state=state,
        nonce=nonce,
        pkce=pkce,
        organization=slug,
        prompt="login",
        idp_hint=alias,
    )
    return TestStarted(test_id, url)


async def _directory(auth: "AuthService", subject: str) -> dict[str, str | None]:
    admin = auth.identity_admin
    if admin is None:
        return {"department": None, "site": None}
    try:
        attributes = await admin.user_attributes(subject)
    except (IdentityAdminUnavailable, IdentityAdminNotConfigured):
        return {"department": None, "site": None}
    department = attributes.get(DEPARTMENT_ATTRIBUTE) or []
    site = attributes.get(SITE_ATTRIBUTE) or []
    return {"department": department[0] if department else None, "site": site[0] if site else None}


async def finish(
    auth: "AuthService", pending: dict[str, Any], *, code: str | None, error: str | None
) -> TestFinished:
    """The test's callback: verify, record the result, end the tested Keycloak session."""
    test = pending["test"]
    tenant_id = uuid.UUID(test["tenant_id"])
    record = await auth.store.get_sso_test(test["id"]) or {}
    outcome: dict[str, Any] = {"status": "failed", "reason": "provider_error"}
    if code and not error:
        client = auth.client("console")
        try:
            tokens = await auth.oidc.exchange_code(client, code=code, verifier=pending["verifier"])
            claims = await auth.oidc.verify_id_token(tokens.id_token)
            validate_claims(
                claims,
                issuer=auth.oidc.issuer,
                client_id=client.client_id,
                nonce=pending["nonce"],
                now=auth.clock.now(),
            )
        except (TokenRejectedError, InvalidTokenError, ClaimsError):
            outcome = {"status": "failed", "reason": "answer_not_verified"}
        else:
            identity = identity_from(claims)
            member = any(m.tenant_id == tenant_id for m in identity.memberships)
            outcome = {
                "status": "passed" if member else "failed",
                "reason": None if member else "not_in_tenant_domains",
                "identity": {
                    "email": identity.email,
                    "name": identity.display_name,
                    **await _directory(auth, identity.subject),
                },
            }
            # A test, not a sign-in: the tested person's Keycloak session ends here.
            await auth._end_keycloak_session(client, tokens.refresh_token)  # noqa: SLF001 - same service, shared helper
    await auth.store.put_sso_test(test["id"], {**record, **outcome}, TEST_TTL)
    return TestFinished(
        redirect_to=auth.origin("console") + DONE_PATH,
        tenant_id=tenant_id,
        admin_user_id=uuid.UUID(test["admin_user_id"]),
        provider_id=uuid.UUID(test["provider_id"]),
        passed=outcome["status"] == "passed",
    )


async def result(
    auth: "AuthService", test_id: str, *, tenant_id: uuid.UUID, provider_id: uuid.UUID
) -> dict[str, Any]:
    """The test's state for the admin's screen (only the tenant and set-up it was started for)."""
    record = await auth.store.get_sso_test(test_id)
    if (
        record is None
        or record.get("tenant_id") != str(tenant_id)
        or record.get("provider_id") != str(provider_id)
    ):
        raise NotFound(code="sso_test_not_found")
    if record["status"] == "pending" and auth.identity_admin is not None:
        try:
            errors = await auth.identity_admin.login_events(LOGIN_ERRORS, record["started_ms"])
        except IdentityAdminUnavailable:
            errors = []
        if errors:
            record = {**record, "status": "failed", "reason": "answer_not_verified"}
    return {
        "status": record["status"],
        "reason": record.get("reason"),
        "identity": record.get("identity"),
    }
