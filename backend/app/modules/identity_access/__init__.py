"""Identity and access module (architecture.md §6.1, §11.1).

BFF login with Keycloak, sessions and users. The BFF lives in `bff/` inside the Core API (D-009).

Public interface for other modules: `UserType`. Sessions reach the rest of the app only as the
`TenantContext` resolved by app.core.tenancy.
"""

from typing import TYPE_CHECKING

import httpx
import valkey.asyncio
from fastapi import FastAPI

from app.core.modules import ModuleSpec
from app.core.tenancy import SESSION_RESOLVER_STATE
from app.modules.identity_access.bff.cookies import cookie_name
from app.modules.identity_access.bff.routes import router
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.infra.crypto import SessionCipher
from app.modules.identity_access.infra.oidc import OidcClient
from app.modules.identity_access.infra.store import SessionStore, ValkeyKeyValue
from app.modules.identity_access.service.auth import AuthService
from app.shared.clock import system_clock

if TYPE_CHECKING:
    from app.core.config import Settings


async def _startup(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    app.state.auth = None
    if not settings.auth_configured:
        return
    if (
        settings.oidc_issuer is None
        or settings.valkey_url is None
        or settings.session_secret is None
    ):
        return  # unreachable: auth_configured checked these; narrows the types for mypy
    http = httpx.AsyncClient(timeout=settings.oidc_timeout_seconds, follow_redirects=False)
    kv = valkey.asyncio.from_url(settings.valkey_url.get_secret_value())  # type: ignore[no-untyped-call]  # valkey-py ships no annotation for from_url
    service = AuthService(
        settings=settings,
        store=SessionStore(
            ValkeyKeyValue(kv), SessionCipher(settings.session_secret.get_secret_value())
        ),
        oidc=OidcClient(settings.oidc_issuer, http),
        database=app.state.db,
        clock=system_clock,
        cookie_name=cookie_name(settings),
    )
    app.state.auth = service
    app.state.auth_clients = (http, kv)
    setattr(app.state, SESSION_RESOLVER_STATE, service.resolve)


async def _shutdown(app: FastAPI) -> None:
    clients = getattr(app.state, "auth_clients", None)
    if clients is not None:
        http, kv = clients
        await http.aclose()
        await kv.aclose()


module = ModuleSpec(
    name="identity_access", routers=[router], on_startup=[_startup], on_shutdown=[_shutdown]
)

__all__ = ["UserType", "module"]
