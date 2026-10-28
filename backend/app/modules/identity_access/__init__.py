"""Identity and access module (architecture.md §6.1, §11.1).

BFF login with Keycloak, sessions and users. The BFF lives in `bff/` inside the Core API (D-009).

Also the authorization policy layer (WP-016, architecture.md §11.2): permission catalogue, roles,
assignments and the one policy service the API, search, realtime and AI agents use.

Public interface for other modules: `UserType`, `Subject`, `ResourceType`, `authorize`,
`authorize_stored`, `scope_filter`, `visible`, `require`, `user_names`, `user_contacts`, and
`get_policy` (FastAPI dependency giving the policy service, e.g. who holds a permission, for
owner pickers). Sessions reach the rest of the app only as the `TenantContext` resolved by
app.core.tenancy; routes declare permissions with app.core.authorization.require_permission.
"""

import functools
import uuid
from typing import TYPE_CHECKING

import httpx
import valkey.asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import (
    AUTHORIZER_STATE,
    register_access_invalidator,
    unregister_access_invalidator,
)
from app.core.logging import get_logger
from app.core.modules import ModuleRegistry, ModuleSpec, discover_modules
from app.core.tenancy import SESSION_RESOLVER_STATE
from app.modules.identity_access.api.access import get_policy
from app.modules.identity_access.api.access import router as access_router
from app.modules.identity_access.api.account import router as account_router
from app.modules.identity_access.api.identity import router as identity_router
from app.modules.identity_access.api.people import access_router as access_settings_router
from app.modules.identity_access.api.people import imports_router, people_router
from app.modules.identity_access.api.routes import router as users_router
from app.modules.identity_access.bff.cookies import cookie_name
from app.modules.identity_access.bff.realtime import router as realtime_router
from app.modules.identity_access.bff.routes import router
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.domain.permissions import (
    IDENTITY_PERMISSIONS,
    RESERVED_PERMISSIONS,
    Catalogue,
)
from app.modules.identity_access.domain.policy import RecordFacts, Subject
from app.modules.identity_access.events import EVENTS
from app.modules.identity_access.infra.crypto import SessionCipher
from app.modules.identity_access.infra.keycloak_admin import KeycloakAdmin
from app.modules.identity_access.infra.oidc import OidcClient
from app.modules.identity_access.infra.store import SessionStore, ValkeyKeyValue
from app.modules.identity_access.service import directory, mfa
from app.modules.identity_access.service.auth import AuthService
from app.modules.identity_access.service.authz_consumer import AUTHZ_INVALIDATION
from app.modules.identity_access.service.directory import (
    MailRecipient,
    NotifiablePerson,
    display_names,
    mail_recipients,
    notifiable_people,
    people_matching,
    user_contacts,
    user_names,
)
from app.modules.identity_access.service.password_policy import PASSWORD_POLICY_APPLY
from app.modules.identity_access.service.people import (
    Placement,
    create_requester_from_mail,
    person_by_email,
    person_placement,
    register_people_usage,
)
from app.modules.identity_access.service.people_import import run_people_imports
from app.modules.identity_access.service.policy import (
    FieldRule,
    PolicyService,
    ResourceType,
    SodRule,
    ValkeySubjectCache,
    authorize,
    authorize_stored,
    require,
    scope_filter,
    visible,
)
from app.modules.identity_access.service.realtime import CHANNELS, ROUTES
from app.modules.identity_access.service.roles import RoleName, role_names
from app.modules.identity_access.service.users import count_technicians
from app.modules.licensing import Feature, entitled_features
from app.modules.organization import memberships
from app.shared.clock import system_clock
from app.shared.realtime import (
    CENTRIFUGO_STATE,
    SESSION_ENDED,
    CentrifugoClient,
    CentrifugoError,
    realtime_user,
)
from app.shared.schedules import ScheduleSpec

log = get_logger(__name__)

if TYPE_CHECKING:
    from app.core.config import Settings


def build_catalogue(registry: ModuleRegistry) -> Catalogue:
    """Every module's permissions plus the reserved ITSM ones, validated (fails startup if bad)."""
    specs = [spec for module in registry.modules for spec in module.permissions]
    return Catalogue.build(specs, frozenset(f.value for f in Feature))


async def _members(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[frozenset[uuid.UUID], frozenset[uuid.UUID]]:
    found = await memberships(session, user_id)
    return found.site_ids, found.group_ids


@functools.cache
def _worker_policy() -> PolicyService:
    """The API's policy compiler for code without the app (workers, jobs): no cache, no pool."""
    registry = ModuleRegistry.from_specs(discover_modules())
    return PolicyService(
        None,
        build_catalogue(registry),
        memberships=_members,
        entitled_features=entitled_features,
        resources={"users": directory.USERS},
    )


async def subject_for(session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> Subject:
    """The user's compiled subject, read from the database now (no cache), for workers and jobs.

    The very compile the API uses (same catalogue, roles, memberships and entitlements), so a
    worker applying a user's scope (exports, scheduled reports; D-052) decides exactly as the API
    would. A deactivated or deleted user gets the subject that may do nothing. `session` is a
    tenant session of `tenant_id`.
    """
    return await _worker_policy().compile(session, tenant_id, user_id)


def _start_policy(app: FastAPI, settings: "Settings") -> None:
    """The policy layer (WP-016): needs the database; caches in Valkey when configured."""
    app.state.policy = None
    setattr(app.state, AUTHORIZER_STATE, None)
    app.state.policy_client = None
    catalogue = build_catalogue(app.state.modules)
    if app.state.db is None:
        return
    cache = None
    if settings.valkey_url is not None:
        client = valkey.asyncio.from_url(settings.valkey_url.get_secret_value())  # type: ignore[no-untyped-call]  # valkey-py ships no annotation for from_url
        app.state.policy_client = client
        cache = ValkeySubjectCache(
            client, prefix=settings.valkey_key_prefix, ttl_seconds=AUTHZ_CACHE_TTL_SECONDS
        )
    policy = PolicyService(
        app.state.db,
        catalogue,
        cache=cache,
        memberships=_members,
        entitled_features=entitled_features,
        resources={"users": directory.USERS},
    )
    app.state.policy = policy
    setattr(app.state, AUTHORIZER_STATE, policy)
    register_access_invalidator(policy.invalidate)


async def _startup(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    _start_policy(app, settings)
    app.state.auth = None
    # Keycloak's admin API as the identity service account (WP-039); None until it is set up.
    app.state.identity_admin = KeycloakAdmin.from_settings(settings)
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
        oidc=OidcClient(settings.oidc_issuer, http, settings.oidc_internal_url),
        database=app.state.db,
        clock=system_clock,
        cookie_name=cookie_name(settings),
    )
    if app.state.policy is not None:
        service.on_roles_mapped = app.state.policy.invalidate

    async def end_realtime(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        # Looked up per call: the realtime client is set up by its own startup (best effort).
        client: CentrifugoClient | None = getattr(app.state, CENTRIFUGO_STATE, None)
        if client is None:
            return
        try:
            await client.disconnect(
                realtime_user(tenant_id, user_id), SESSION_ENDED, "access ended"
            )
        except CentrifugoError:
            log.warning("realtime_disconnect_failed", exc_info=True)

    service.end_realtime = end_realtime
    service.identity_admin = app.state.identity_admin
    app.state.auth = service
    app.state.auth_clients = (http, kv)
    setattr(app.state, SESSION_RESOLVER_STATE, service.resolve)


async def _shutdown(app: FastAPI) -> None:
    policy = getattr(app.state, "policy", None)
    if policy is not None:
        unregister_access_invalidator(policy.invalidate)
    policy_client = getattr(app.state, "policy_client", None)
    if policy_client is not None:
        await policy_client.aclose()
    identity_admin = getattr(app.state, "identity_admin", None)
    if identity_admin is not None:
        await identity_admin.close()
    clients = getattr(app.state, "auth_clients", None)
    if clients is not None:
        http, kv = clients
        await http.aclose()
        await kv.aclose()


module = ModuleSpec(
    name="identity_access",
    routers=[
        router,
        people_router,
        users_router,
        imports_router,
        access_router,
        access_settings_router,
        identity_router,
        account_router,
        realtime_router,
    ],
    on_startup=[_startup],
    on_shutdown=[_shutdown],
    events=EVENTS,
    consumers=[AUTHZ_INVALIDATION, PASSWORD_POLICY_APPLY, mfa.MFA_ROLES],
    # Realtime (WP-011): who may join which channel, and what identity events show on screens.
    channels=CHANNELS,
    realtime=ROUTES,
    # Own permissions plus the reserved ITSM ones (moved to their modules as they arrive).
    permissions=IDENTITY_PERMISSIONS + RESERVED_PERMISSIONS,
    # Licensed technician seats (WP-009); requesters are never counted.
    usage_counters={"technicians": count_technicians},
    schedules=[
        ScheduleSpec("identity_access__people_imports", 5, run_people_imports),
        # Past the MFA grace period: Keycloak's enrol actions (WP-039 session 3, REQ-SEC-024).
        ScheduleSpec("identity_access__mfa_enforce", 3600, mfa.enforce_schedule),
    ],
)

# Compiled permissions are refreshed through events at the latest after this (seconds); the
# generation bump makes changes visible far sooner (see service/policy.py).
AUTHZ_CACHE_TTL_SECONDS = 300

register_people_usage()

__all__ = [
    "FieldRule",
    "MailRecipient",
    "NotifiablePerson",
    "Placement",
    "PolicyService",
    "RecordFacts",
    "ResourceType",
    "RoleName",
    "SodRule",
    "Subject",
    "UserType",
    "authorize",
    "authorize_stored",
    "create_requester_from_mail",
    "display_names",
    "get_policy",
    "mail_recipients",
    "module",
    "notifiable_people",
    "people_matching",
    "person_by_email",
    "person_placement",
    "require",
    "role_names",
    "scope_filter",
    "subject_for",
    "user_contacts",
    "user_names",
    "visible",
]
