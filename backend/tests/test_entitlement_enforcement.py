"""Route enforcement over HTTP: feature gates, read-only mode, grace warnings (WP-009).

A sample module declares `feature="esm"` (Enterprise only) and gets gated without any code in its
routes; a second sample module has no feature and shows the read-only rules on their own. The same
scenarios run with the test provider and with an unsigned dev licence file, proving gating behaves
identically whichever provider supplies the entitlement (the subscription provider runs the same
checks against PostgreSQL in tests/db/test_entitlements.py).
"""

import json
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.core.entitlements import read_only_exempt
from app.core.modules import ModuleRegistry, ModuleSpec
from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext
from app.main import create_app
from app.modules import licensing, system
from app.modules.licensing import (
    Edition,
    Entitlement,
    EntitlementService,
    LimitKey,
    StaticProvider,
    Term,
    start_service,
)
from app.modules.licensing.domain.licence import LicenceRejectedError
from app.modules.licensing.infra.providers import (
    DevLicenceVerifier,
    LicenceFileProvider,
    NoInstallationCheck,
)
from app.modules.licensing.service.gate import DAYS_LEFT_HEADER, STATE_HEADER
from conftest import make_settings

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
DAY = timedelta(days=1)
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def sample_router(prefix: str) -> APIRouter:
    router = APIRouter(prefix=prefix)

    @router.get("/items")
    async def list_items() -> dict[str, str]:
        return {"ok": "read"}

    for method in WRITE_METHODS:
        router.add_api_route("/items", _write, methods=[method])

    @router.post("/export")
    @read_only_exempt
    async def export() -> dict[str, str]:
        return {"ok": "export"}

    return router


async def _write() -> dict[str, str]:
    return {"ok": "write"}


SAMPLE_ESM = ModuleSpec(name="sample_esm", routers=[sample_router("/esm")], feature="esm")
SAMPLE_CORE = ModuleSpec(name="sample_core", routers=[sample_router("/core")])
REGISTRY = ModuleRegistry.from_specs([licensing.module, system.module, SAMPLE_ESM, SAMPLE_CORE])


async def fake_session(request: Request) -> TenantContext | None:
    tenant = request.headers.get("x-test-tenant")
    if tenant is None:
        return None
    roles = frozenset(filter(None, request.headers.get("x-test-roles", "").split(",")))
    return TenantContext(uuid.UUID(tenant), uuid.uuid4(), roles=roles)


def entitlement(edition: Edition = Edition.ENTERPRISE, **term: Any) -> Entitlement:  # noqa: ANN401
    values = {"starts_at": NOW - 100 * DAY, **term}
    return Entitlement.build(edition, term=Term(**values))


def licence_file(tmp_path: Path, **fields: Any) -> Path:  # noqa: ANN401
    path = tmp_path / f"licence-{uuid.uuid4().hex}.json"
    document = {
        "licence_id": "LIC-DEV-1",
        "customer": "Dev",
        "edition": "enterprise",
        "issued_at": (NOW - 100 * DAY).date().isoformat(),
        **fields,
    }
    path.write_text(json.dumps(document))
    return path


ProviderFactory = Callable[[Entitlement, Path], Any]


def static_provider(value: Entitlement, tmp_path: Path) -> StaticProvider:
    del tmp_path
    return StaticProvider(default=value)


def file_provider(value: Entitlement, tmp_path: Path) -> LicenceFileProvider:
    """A dev licence file carrying the same edition and term as `value`."""
    assert value.edition is not None
    assert value.term is not None
    fields: dict[str, Any] = {
        "edition": value.edition.value,
        "issued_at": value.term.starts_at.date().isoformat(),
        "grace_days": value.term.grace_days,
    }
    if value.term.expires_at is not None:
        # The file names the last valid day; the domain stores the instant after it.
        fields["expires_at"] = (value.term.expires_at - DAY).date().isoformat()
    return LicenceFileProvider(
        licence_file(tmp_path, **fields),
        verifier=DevLicenceVerifier(allow_unsigned=True),
        installation=NoInstallationCheck(),
    )


@pytest_asyncio.fixture
async def app() -> AsyncIterator[FastAPI]:
    application = create_app(make_settings(), registry=REGISTRY)
    async with application.router.lifespan_context(application):
        setattr(application.state, SESSION_RESOLVER_STATE, fake_session)
        yield application


def use(app: FastAPI, provider: Any, now: datetime = NOW) -> EntitlementService:  # noqa: ANN401
    service = EntitlementService(provider, clock=lambda: now)
    start_service(app, service)
    return service


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def as_tenant(roles: str = "technician") -> dict[str, str]:
    return {"X-Test-Tenant": str(uuid.uuid4()), "X-Test-Roles": roles}


PROVIDERS = pytest.mark.parametrize("make_provider", [static_provider, file_provider])


# --- feature gates --------------------------------------------------------------------------------


@PROVIDERS
async def test_module_without_the_feature_is_refused_for_reads_and_writes(
    app: FastAPI, client: AsyncClient, tmp_path: Path, make_provider: ProviderFactory
) -> None:
    use(app, make_provider(entitlement(Edition.PROFESSIONAL), tmp_path))
    headers = as_tenant()
    for method in ("GET", *WRITE_METHODS):
        response = await client.request(method, "/api/v1/esm/items", headers=headers)
        assert response.status_code == 403, method
        body = response.json()
        assert (body["code"], body["message_key"]) == (
            "entitlement_required",
            "errors.entitlement_required",
        )
        assert body["params"] == {"feature": "esm"}  # the UI shows label feature.esm
    # Modules without a feature are unaffected.
    assert (await client.get("/api/v1/core/items", headers=headers)).status_code == 200


@PROVIDERS
async def test_module_with_the_feature_works(
    app: FastAPI, client: AsyncClient, tmp_path: Path, make_provider: ProviderFactory
) -> None:
    use(app, make_provider(entitlement(Edition.ENTERPRISE), tmp_path))
    headers = as_tenant()
    for method in ("GET", *WRITE_METHODS):
        response = await client.request(method, "/api/v1/esm/items", headers=headers)
        assert response.status_code == 200, method


async def test_gate_decides_per_tenant(app: FastAPI, client: AsyncClient) -> None:
    enterprise, professional = uuid.uuid4(), uuid.uuid4()
    use(
        app,
        StaticProvider(
            {
                enterprise: entitlement(Edition.ENTERPRISE),
                professional: entitlement(Edition.PROFESSIONAL),
            }
        ),
    )
    for tenant, expected in ((enterprise, 200), (professional, 403)):
        response = await client.get("/api/v1/esm/items", headers={"X-Test-Tenant": str(tenant)})
        assert response.status_code == expected


async def test_health_and_login_need_no_entitlement(app: FastAPI, client: AsyncClient) -> None:
    use(app, StaticProvider())  # nobody is entitled to anything
    assert (await client.get("/api/v1/health")).status_code == 200


async def test_gated_route_without_a_session_is_401_not_403(
    app: FastAPI, client: AsyncClient
) -> None:
    use(app, StaticProvider(default=entitlement()))
    assert (await client.get("/api/v1/esm/items")).json()["code"] == "unauthenticated"


# --- read-only mode (§13.6) -----------------------------------------------------------------------


@PROVIDERS
async def test_read_only_blocks_every_write_while_reads_and_exports_work(
    app: FastAPI, client: AsyncClient, tmp_path: Path, make_provider: ProviderFactory
) -> None:
    # Expired 30 days ago with 14 days of grace: read-only for 16 days now.
    use(app, make_provider(entitlement(expires_at=NOW - 30 * DAY, grace_days=14), tmp_path))
    headers = as_tenant("tenant_admin,technician")
    for prefix in ("/api/v1/esm", "/api/v1/core"):
        assert (await client.get(f"{prefix}/items", headers=headers)).status_code == 200
        assert (await client.head(f"{prefix}/items", headers=headers)).status_code in {200, 405}
        assert (await client.post(f"{prefix}/export", headers=headers)).json() == {"ok": "export"}
        for method in WRITE_METHODS:
            response = await client.request(method, f"{prefix}/items", headers=headers)
            assert response.status_code == 403, (prefix, method)
            body = response.json()
            assert (body["code"], body["message_key"], body["params"]) == (
                "read_only_mode",
                "errors.read_only_mode",
                {"reason": "expired"},
            )


async def test_suspended_and_missing_plans_are_read_only_too(
    app: FastAPI, client: AsyncClient
) -> None:
    suspended, nothing = uuid.uuid4(), uuid.uuid4()
    use(
        app,
        StaticProvider(
            {suspended: Entitlement.build(Edition.ENTERPRISE, term=Term(NOW), suspended=True)}
        ),
    )
    for tenant, reason in ((suspended, "suspended"), (nothing, "no_entitlement")):
        headers = {"X-Test-Tenant": str(tenant)}
        assert (await client.get("/api/v1/core/items", headers=headers)).status_code == 200
        response = await client.post("/api/v1/core/items", headers=headers)
        assert (response.status_code, response.json()["params"]) == (403, {"reason": reason})


# --- grace (§13.6) --------------------------------------------------------------------------------


@PROVIDERS
async def test_grace_keeps_writes_working_and_warns_admins_only(
    app: FastAPI, client: AsyncClient, tmp_path: Path, make_provider: ProviderFactory
) -> None:
    use(app, make_provider(entitlement(expires_at=NOW - 3 * DAY, grace_days=14), tmp_path))
    tenant = str(uuid.uuid4())
    admin = {"X-Test-Tenant": tenant, "X-Test-Roles": "tenant_admin,technician"}
    technician = {"X-Test-Tenant": tenant, "X-Test-Roles": "technician"}
    as_admin = await client.post("/api/v1/core/items", headers=admin)
    assert as_admin.status_code == 200
    assert as_admin.headers[STATE_HEADER] == "grace"
    assert as_admin.headers[DAYS_LEFT_HEADER] == "11"
    as_technician = await client.post("/api/v1/core/items", headers=technician)
    assert as_technician.status_code == 200
    assert STATE_HEADER not in as_technician.headers


async def test_active_plan_sends_no_warning(app: FastAPI, client: AsyncClient) -> None:
    use(app, StaticProvider(default=entitlement()))
    response = await client.get("/api/v1/core/items", headers=as_tenant("tenant_admin"))
    assert STATE_HEADER not in response.headers


# --- provider selection and the production rule ---------------------------------------------------


async def test_unknown_module_feature_stops_startup() -> None:
    bad = ModuleSpec(name="bad", feature="teleport")
    application = create_app(
        make_settings(), registry=ModuleRegistry.from_specs([licensing.module, bad])
    )
    with pytest.raises(licensing.ModuleFeatureError, match="teleport"):
        async with application.router.lifespan_context(application):
            pass


async def test_unsigned_licence_is_rejected_in_production_and_startup_fails(
    production_settings: Callable[..., Any], tmp_path: Path
) -> None:
    settings = production_settings(
        entitlement_provider="licence_file", licence_file=licence_file(tmp_path)
    )
    application = create_app(settings, registry=REGISTRY)
    with pytest.raises(LicenceRejectedError) as caught:
        async with application.router.lifespan_context(application):
            pass
    assert caught.value.reason == "licence_unsigned"


async def test_unsigned_licence_is_accepted_in_dev_and_test(tmp_path: Path) -> None:
    for profile in ("dev", "test"):
        settings = make_settings(
            profile=profile,
            entitlement_provider="licence_file",
            licence_file=licence_file(tmp_path),
        )
        provider = licensing.build_provider(settings, database=None)
        assert isinstance(provider, LicenceFileProvider)
        assert (await provider.load(uuid.uuid4())).edition is Edition.ENTERPRISE


def test_signed_licences_wait_for_the_licence_core(tmp_path: Path) -> None:
    """Until WP-013 nothing can verify a signature, so a signed file is refused everywhere."""
    settings = make_settings(
        entitlement_provider="licence_file",
        licence_file=licence_file(tmp_path, signature="ed25519:abc"),
    )
    with pytest.raises(LicenceRejectedError) as caught:
        licensing.build_provider(settings, database=None)
    assert caught.value.reason == "signature_verification_unavailable"


def test_missing_licence_file_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(
        entitlement_provider="licence_file", licence_file=tmp_path / "missing.json"
    )
    with pytest.raises(LicenceRejectedError) as caught:
        licensing.build_provider(settings, database=None)
    assert caught.value.reason == "licence_unreadable"


def test_licence_file_setting_is_required_for_that_provider() -> None:
    with pytest.raises(ValueError, match="SUPPORTX_LICENCE_FILE"):
        make_settings(entitlement_provider="licence_file")


def test_subscription_provider_needs_a_database() -> None:
    assert licensing.build_provider(make_settings(), database=None) is None


async def test_without_any_entitlement_service_requests_pass(client: AsyncClient) -> None:
    """No database in a dev/test run: no gate (production always has a database)."""
    assert (await client.post("/api/v1/core/items", headers=as_tenant())).status_code == 200


async def test_licence_reload_picks_up_a_new_file(tmp_path: Path) -> None:
    path = licence_file(tmp_path, edition="essentials")
    provider = LicenceFileProvider(
        path, verifier=DevLicenceVerifier(allow_unsigned=True), installation=NoInstallationCheck()
    )
    assert (await provider.load(uuid.uuid4())).edition is Edition.ESSENTIALS
    path.write_text(path.read_text().replace("essentials", "professional"))
    provider.reload()
    entitled = await provider.load(uuid.uuid4())
    assert entitled.edition is Edition.PROFESSIONAL
    assert entitled.limit(LimitKey.TECHNICIANS) == 50
