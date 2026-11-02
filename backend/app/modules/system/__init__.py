"""System module: liveness and readiness of the API process (ADR-018), and platform services.

Health: no tables, no events; one consumer, the dev-only event logger (service/dev_event_log.py).
It is also the reference example of the module registry contract: one `MAIL_SEND = ConsumerSpec(
    name="system__mail_send",
    event_types=(MailQueued.event_type,),
    handler=mail.on_mail_queued,
    ack_wait_seconds=120,  # a slow mail server, a 10 MB attachment
)

module = ModuleSpec(...)`
declaring routers, lifecycle hooks and consumers.

Platform services (architecture.md §6.8) live in `app/shared` and own their tables there; only
modules are registered, so this module mounts them: files (WP-022, ADR-028, `api/files.py`,
`service/files.py`): routes, the scan consumer, schedules, events, realtime, the `files.manage`
permission, the `storage_gb` usage counter and the quota source.
"""

from fastapi import FastAPI

from app.core.authorization import PermissionSpec
from app.core.config import Settings
from app.core.modules import ModuleSpec
from app.modules.system.api.files import MANAGE as FILES_MANAGE
from app.modules.system.api.files import router as files_router
from app.modules.system.api.routes import router
from app.modules.system.domain.readiness import DependencyProbe
from app.modules.system.infra.probes import (
    KeycloakProbe,
    NatsProbe,
    PostgresProbe,
    ValkeyProbe,
    WorkerHeartbeatProbe,
)
from app.modules.system.service import files, mail
from app.modules.system.service.dev_event_log import DEV_EVENT_LOGGER
from app.modules.system.service.readiness import ReadinessService
from app.shared.events import BusNames, ConsumerSpec
from app.shared.files.events import EVENTS as FILE_EVENTS
from app.shared.files.events import FileUploaded
from app.shared.files.ports import register_quota
from app.shared.files.service.core import FileServices
from app.shared.mail.events import EVENTS as MAIL_EVENTS
from app.shared.mail.events import MailQueued
from app.shared.schedules import ScheduleSpec


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
        # The realm as this process reaches it (inside a cluster: the internal URL, WP-014).
        probes.append(KeycloakProbe(settings.oidc_internal_url or settings.oidc_issuer))
    return ReadinessService(
        probes,
        not_configured=not_configured,
        informational=_worker_probes(settings),
        timeout=settings.readiness_timeout_seconds,
    )


def _worker_probes(settings: Settings) -> list[DependencyProbe]:
    """Heartbeats of the event workers (informational): relay, consumers, realtime fan-out."""
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
            backlog_after_s=settings.event_backlog_stalled_seconds if kind == "relay" else None,
        )
        for name, kind in (
            ("outbox_relay", "relay"),
            ("event_consumers", "consumers"),
            ("realtime_fanout", "fanout"),
        )
    ]


async def _startup(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    app.state.readiness = build_readiness_service(settings)
    # A malformed files key ring fails startup here, loudly, rather than at the first upload.
    setattr(app.state, files.FILES_STATE, FileServices.from_settings(settings))
    register_quota(files.storage_limit_bytes)


FILE_SCAN = ConsumerSpec(
    name="system__file_scan",
    event_types=(FileUploaded.event_type,),
    handler=files.on_file_uploaded,
    # A 100 MB file through clamd can take a while; redeliveries must not overlap a running scan.
    ack_wait_seconds=300,
)

MAIL_SEND = ConsumerSpec(
    name="system__mail_send",
    event_types=(MailQueued.event_type,),
    handler=mail.on_mail_queued,
    ack_wait_seconds=120,  # a slow mail server, a 10 MB attachment
)

module = ModuleSpec(
    name="system",
    routers=[router, files_router],
    on_startup=[_startup],
    consumers=[DEV_EVENT_LOGGER, FILE_SCAN, MAIL_SEND],
    events=(*FILE_EVENTS, *MAIL_EVENTS),
    permissions=[PermissionSpec(FILES_MANAGE)],
    realtime=files.REALTIME,
    schedules=[
        ScheduleSpec("system__files_scan_sweep", 300, files.scan_sweep),
        ScheduleSpec("system__files_purge", 3600, files.purge),
        ScheduleSpec("system__files_scanner_check", 3600, files.check_scanner),
        ScheduleSpec("system__mail_retry", 60, mail.retry),
        ScheduleSpec("system__mail_purge", 3600, mail.purge),
    ],
    usage_counters={"storage_gb": files.storage_gb_used},
)

__all__ = ["module"]
