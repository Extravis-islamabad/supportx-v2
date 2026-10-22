"""System module: liveness and readiness of the API process (ADR-018).

It owns no tables and publishes no events. It declares one consumer, the dev-only event logger
(service/dev_event_log.py). It is also the reference example of the module registry contract:
one `module = ModuleSpec(...)` declaring routers, lifecycle hooks and consumers.
"""

from fastapi import FastAPI

from app.core.config import Settings
from app.core.modules import ModuleSpec
from app.modules.system.api.routes import router
from app.modules.system.domain.readiness import DependencyProbe
from app.modules.system.infra.probes import (
    KeycloakProbe,
    NatsProbe,
    PostgresProbe,
    ValkeyProbe,
    WorkerHeartbeatProbe,
)
from app.modules.system.service.dev_event_log import DEV_EVENT_LOGGER
from app.modules.system.service.readiness import ReadinessService
from app.shared.events import BusNames


def build_readiness_service(settings: Settings) -> ReadinessService:
    """Probe every configured dependency (PostgreSQL, Valkey, NATS, Keycloak).

    Unconfigured dependencies are reported as such, not skipped. The event workers are
    reported from their heartbeats as informational checks.
    """
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
    if settings.oidc_issuer is None:
        not_configured.append("keycloak")
    else:
        probes.append(KeycloakProbe(settings.oidc_issuer))
    return ReadinessService(
        probes,
        not_configured=not_configured,
        informational=_worker_probes(settings),
        timeout=settings.readiness_timeout_seconds,
    )


def _worker_probes(settings: Settings) -> list[DependencyProbe]:
    """Heartbeats of the outbox relay and the consumer worker (informational, WP-007)."""
    if settings.nats_url is None:
        return []  # already reported as nats: not_configured
    bucket = BusNames(settings.events_namespace).heartbeat_bucket
    return [
        WorkerHeartbeatProbe(
            settings.nats_url.get_secret_value(),
            name=name,
            bucket=bucket,
            kind=kind,
            stale_after_s=settings.heartbeat_stale_seconds,
        )
        for name, kind in (("outbox_relay", "relay"), ("event_consumers", "consumers"))
    ]


async def _startup(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    app.state.readiness = build_readiness_service(settings)


module = ModuleSpec(
    name="system", routers=[router], on_startup=[_startup], consumers=[DEV_EVENT_LOGGER]
)

__all__ = ["module"]
