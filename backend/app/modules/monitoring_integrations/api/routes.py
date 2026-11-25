"""Monitoring integrations API (WP-053 S6): MonetX connections, topology runs and CI health.

Connections need `monitoring.manage`: create, change and remove carry RecentAuth (they hold the
API token), are audited and take Idempotency-Key / If-Match. The token goes in, never out: an
answer only says `has_secret`. Health needs `cmdb.view` and answers only for the CIs the reader
may see. Every route is rate-limited per user and per tenant (`monitoring`).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.config import Settings
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.core.recent_auth import RecentAuth
from app.modules.audit import audited
from app.modules.identity_access import Subject
from app.modules.monitoring_integrations.domain.monitoring import HEALTH_IDS_MAX
from app.modules.monitoring_integrations.infra.models import TopologyRun
from app.modules.monitoring_integrations.service import connections as service
from app.modules.monitoring_integrations.service import health as health_service
from app.modules.monitoring_integrations.service import topology
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

MANAGE = service.MANAGE
CMDB_VIEW = "cmdb.view"
Responses = dict[int | str, dict[str, object]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission, or MonetX not licensed."},
}
NOT_FOUND: Responses = {
    404: {"model": ProblemDetail, "description": "No such connection."},
}
CONFLICT: Responses = {409: {"model": ProblemDetail, "description": "Stale If-Match, or taken."}}

connections_router = APIRouter(
    prefix="/monitoring/connections",
    tags=["monitoring"],
    dependencies=[Depends(rate_limit("monitoring"))],
    responses=RESPONSES,
)
health_router = APIRouter(
    prefix="/monitoring/health",
    tags=["monitoring"],
    dependencies=[Depends(rate_limit("monitoring"))],
    responses=RESPONSES,
)
Manage = Annotated[Subject, Depends(require_permission(MANAGE))]
Viewer = Annotated[Subject, Depends(require_permission(CMDB_VIEW))]


def _app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(_app_settings)]


class MonitoringConnectionIn(BaseModel):
    """A MonetX connection. `token` is write-only: send it to set or replace it."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=service.NAME_MAX)
    base_url: str = Field(min_length=1, max_length=service.URL_MAX)
    token: str | None = Field(default=None, min_length=1, max_length=service.TOKEN_MAX)
    enabled: bool = True
    site_map: dict[str, uuid.UUID] = Field(
        default_factory=dict, description="MonetX group → SupportX site."
    )

    def values(self) -> dict[str, Any]:
        """The stored fields (never the token)."""
        return {
            "name": self.name,
            "base_url": self.base_url,
            "enabled": self.enabled,
            "site_map": {k: str(v) for k, v in self.site_map.items()},
        }


class MonitoringConnectionOut(BaseModel):
    """A connection: never its token, only whether one is set."""

    id: uuid.UUID
    name: str
    base_url: str
    enabled: bool
    has_secret: bool
    site_map: dict[str, str]
    last_run_at: datetime | None
    last_error_code: str | None
    version: int

    @classmethod
    def of(cls, view: service.ConnectionView) -> "MonitoringConnectionOut":
        """From the service's view."""
        return cls(**view.__dict__)


class MonitoringConnectionTestOut(BaseModel):
    """A connection test: ok, or a labelled reason code."""

    ok: bool
    reason: str | None = None


class TopologyRunOut(BaseModel):
    """One topology import."""

    id: uuid.UUID
    state: str
    started_at: datetime
    finished_at: datetime | None
    counts: dict[str, int]
    error_code: str | None

    @classmethod
    def of(cls, run: TopologyRun) -> "TopologyRunOut":
        """From a run row."""
        return cls(
            id=run.id,
            state=run.state,
            started_at=run.started_at,
            finished_at=run.finished_at,
            counts={str(k): int(v) for k, v in (run.counts or {}).items()},
            error_code=run.error_code,
        )


class CiHealthOut(BaseModel):
    """One CI's health: a state code, since when, how many problems, and why if unknown."""

    ci_id: uuid.UUID
    state: str
    since: datetime | None
    problem_count: int
    reason: str | None


class CiHealthList(BaseModel):
    """Health of the CIs asked for that the reader may see (others are absent)."""

    items: list[CiHealthOut]


@connections_router.get("", summary="List MonetX connections")
async def list_connections(
    session: TenantSession, subject: Manage
) -> list[MonitoringConnectionOut]:
    """Every connection of the tenant."""
    del subject
    return [MonitoringConnectionOut.of(v) for v in await service.list_connections(session)]


@connections_router.post(
    "",
    summary="Add a MonetX connection",
    status_code=status.HTTP_201_CREATED,
    response_model=MonitoringConnectionOut,
    responses=CONFLICT,
    dependencies=[
        RecentAuth,
        audited("monitoring.connection_created", object_type="monitoring_connection"),
    ],
)
async def create_connection(
    body: MonitoringConnectionIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    settings: AppSettings,
) -> Response:
    """Send an Idempotency-Key: a retried request returns the same 201."""
    del subject

    async def run() -> Created:
        view = await service.create_connection(session, settings, body.values(), token=body.token)
        out = MonitoringConnectionOut.of(view)
        return Created(body=out, headers={"ETag": f'"{out.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@connections_router.get("/{connection_id}", summary="Get a MonetX connection", responses=NOT_FOUND)
async def get_connection(
    connection_id: uuid.UUID, session: TenantSession, subject: Manage, response: Response
) -> MonitoringConnectionOut:
    """One connection, with its version as ETag."""
    del subject
    out = MonitoringConnectionOut.of(await service.get_connection(session, connection_id))
    set_etag(response, out.version)
    return out


@connections_router.put(
    "/{connection_id}",
    summary="Change a MonetX connection",
    responses={**NOT_FOUND, **CONFLICT},
    dependencies=[
        RecentAuth,
        audited(
            "monitoring.connection_changed",
            object_type="monitoring_connection",
            object_param="connection_id",
        ),
    ],
)
async def update_connection(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    connection_id: uuid.UUID,
    body: MonitoringConnectionIn,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    settings: AppSettings,
) -> MonitoringConnectionOut:
    """If-Match: the version you read. Leave `token` out to keep the current one."""
    del subject
    view = await service.update_connection(
        session,
        settings,
        connection_id,
        body.values(),
        token=body.token,
        expected_version=version,
    )
    out = MonitoringConnectionOut.of(view)
    set_etag(response, out.version)
    return out


@connections_router.delete(
    "/{connection_id}",
    summary="Remove a MonetX connection",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**NOT_FOUND, **CONFLICT},
    dependencies=[
        RecentAuth,
        audited(
            "monitoring.connection_removed",
            object_type="monitoring_connection",
            object_param="connection_id",
        ),
    ],
)
async def remove_connection(
    connection_id: uuid.UUID, session: TenantSession, subject: Manage, version: ExpectedVersion
) -> Response:
    """Stop reading this MonetX. Its CIs stay; its token is forgotten."""
    del subject
    await service.remove_connection(session, connection_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@connections_router.get(
    "/{connection_id}/test", summary="Test a MonetX connection", responses=NOT_FOUND
)
async def test_connection(
    connection_id: uuid.UUID, session: TenantSession, subject: Manage, settings: AppSettings
) -> MonitoringConnectionTestOut:
    """One read of MonetX (GET only). A failure is a labelled reason, never MonetX's text."""
    del subject
    reason = await service.test_connection(session, settings, connection_id)
    return MonitoringConnectionTestOut(ok=reason is None, reason=reason)


@connections_router.get(
    "/{connection_id}/runs", summary="List topology imports", responses=NOT_FOUND
)
async def list_runs(
    connection_id: uuid.UUID, session: TenantSession, subject: Manage
) -> list[TopologyRunOut]:
    """The connection's latest imports, newest first."""
    del subject
    await service.get_connection(session, connection_id)  # 404 when gone
    return [TopologyRunOut.of(r) for r in await topology.list_runs(session, connection_id)]


@connections_router.post(
    "/{connection_id}/runs",
    summary="Import the topology now",
    status_code=status.HTTP_202_ACCEPTED,
    responses=NOT_FOUND,
    dependencies=[
        audited(
            "monitoring.topology_requested",
            object_type="monitoring_connection",
            object_param="connection_id",
        )
    ],
)
async def request_run(
    connection_id: uuid.UUID, session: TenantSession, subject: Manage
) -> TopologyRunOut:
    """Starts within a minute; a run already waiting is returned instead of a second one."""
    del subject
    return TopologyRunOut.of(await topology.request_run(session, connection_id))


@health_router.get("", summary="Health of CIs from MonetX")
async def get_health(
    session: TenantSession,
    subject: Viewer,
    settings: AppSettings,
    ci_ids: Annotated[list[uuid.UUID], Query(min_length=1, max_length=HEALTH_IDS_MAX)],
) -> CiHealthList:
    """Up to 200 CIs. A CI you may not see is absent; one MonetX doesn't watch is `unmonitored`."""
    found = await health_service.health_for(session, subject, settings, ci_ids)
    return CiHealthList(
        items=[
            CiHealthOut(
                ci_id=ci_id,
                state=h.state.value,
                since=h.since,
                problem_count=h.problem_count,
                reason=h.reason,
            )
            for ci_id, h in found.items()
        ]
    )


ROUTERS = (connections_router, health_router)
