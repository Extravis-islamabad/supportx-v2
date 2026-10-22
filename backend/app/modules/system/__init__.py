"""System module: liveness and readiness of the API process (ADR-018).

It owns no tables and publishes no events. It is also the reference example of the module
registry contract: one `module = ModuleSpec(...)` declaring routers and lifecycle hooks.
"""

from typing import TYPE_CHECKING

from fastapi import FastAPI

from app.core.config import Settings
from app.core.modules import ModuleSpec
from app.modules.system.api.routes import router
from app.modules.system.infra.probes import NatsProbe, PostgresProbe, ValkeyProbe
from app.modules.system.service.readiness import ReadinessService

if TYPE_CHECKING:
    from app.modules.system.domain.readiness import DependencyProbe


def build_readiness_service(settings: Settings) -> ReadinessService:
    """Probe every configured dependency; unconfigured ones are reported, not skipped."""
    probes: list[DependencyProbe] = []
    not_configured: list[str] = []
    for name, url, probe_type in (
        ("postgres", settings.database_url, PostgresProbe),
        ("valkey", settings.valkey_url, ValkeyProbe),
        ("nats", settings.nats_url, NatsProbe),
    ):
        if url is None:
            not_configured.append(name)
        else:
            probes.append(probe_type(url.get_secret_value()))
    return ReadinessService(
        probes, not_configured=not_configured, timeout=settings.readiness_timeout_seconds
    )


async def _startup(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    app.state.readiness = build_readiness_service(settings)


module = ModuleSpec(name="system", routers=[router], on_startup=[_startup])

__all__ = ["module"]
