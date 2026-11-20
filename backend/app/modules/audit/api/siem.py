"""Admin > Audit > Security monitoring: where entries stream (REQ-AUD-011, WP-057 S5a).

Every route needs `audit.manage` (without it, 404: the audit log does not exist for you);
adding and changing also need the `siem_stream` feature (the service checks). Writes ask for a
recent sign-in, take If-Match or an Idempotency-Key, and are audited with codes only. A webhook's
signing secret is in the answer once, when it is made (Cache-Control: no-store); nothing else
ever reads a secret back: the read model says only whether one is set.
"""

import json
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.core.recent_auth import RecentAuth
from app.modules.audit.api.routes import MANAGE, _hidden
from app.modules.audit.domain import siem as domain
from app.modules.audit.infra.models import SiemDestination
from app.modules.audit.service import siem
from app.modules.audit.service.recording import AuditNote, audited
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/audit/siem",
    tags=["audit"],
    dependencies=[Depends(rate_limit("audit"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        404: {"model": ProblemDetail, "description": "No such destination (or no audit.manage)."},
    },
)
Manage = Annotated[Any, Depends(_hidden(MANAGE))]
NO_STORE = {"Cache-Control": "no-store"}

SiemKind = domain.SiemKind
SiemFormat = domain.SiemFormat
SiemStream = domain.SiemStream


class SiemDestinationIn(BaseModel):
    """A destination; PEMs: omitted = unchanged, "" = cleared (never read back)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    kind: SiemKind
    format: SiemFormat = SiemFormat.JSON
    host: str | None = Field(default=None, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65535)
    url: str | None = Field(default=None, max_length=2048)
    streams: list[SiemStream] = Field(default_factory=lambda: [SiemStream.AUDIT], min_length=1)
    enabled: bool = True
    ca_pem: str | None = Field(default=None, max_length=65536)
    client_cert_pem: str | None = Field(default=None, max_length=65536)
    client_key_pem: str | None = Field(default=None, max_length=65536)

    def data(self) -> siem.DestinationInput:
        """The service's input."""
        return siem.DestinationInput(
            name=self.name,
            kind=self.kind,
            format=self.format,
            host=self.host,
            port=self.port,
            url=self.url,
            streams=tuple(dict.fromkeys(self.streams)),
            enabled=self.enabled,
            ca_pem=self.ca_pem,
            client_cert_pem=self.client_cert_pem,
            client_key_pem=self.client_key_pem,
        )


class SiemHealthOut(BaseModel):
    """How a destination is doing (the error is a code: labels `siem_error.<code>`)."""

    behind: int = Field(description="Audit entries sealed but not yet acknowledged.")
    last_success_at: datetime | None
    last_error_code: str | None
    last_error_at: datetime | None
    failing_since: datetime | None


class SiemDestinationOut(BaseModel):
    """A destination as an admin sees it: whether secrets are set, never their values."""

    id: uuid.UUID
    name: str
    kind: SiemKind
    format: SiemFormat
    host: str | None
    port: int | None
    url: str | None
    streams: list[SiemStream]
    enabled: bool
    has_secret: bool
    rotating: bool = Field(description="A previous signing secret still signs (a rotation).")
    has_ca: bool
    has_client_cert: bool
    health: SiemHealthOut
    version: int

    @classmethod
    def of(cls, row: SiemDestination, health: siem.Health) -> "SiemDestinationOut":
        """From the row and its health."""
        return cls(
            id=row.id,
            name=row.name,
            kind=SiemKind(row.kind),
            format=SiemFormat(row.format),
            host=row.host,
            port=row.port,
            url=row.url,
            streams=[SiemStream(s) for s in row.streams],
            enabled=row.enabled,
            has_secret=row.secret_sealed is not None,
            rotating=row.previous_secret_sealed is not None,
            has_ca=row.ca_pem_sealed is not None,
            has_client_cert=row.client_cert_sealed is not None,
            health=SiemHealthOut(
                behind=health.behind,
                last_success_at=health.last_success_at,
                last_error_code=health.last_error_code,
                last_error_at=health.last_error_at,
                failing_since=health.failing_since,
            ),
            version=row.version,
        )


class SiemDestinationMadeOut(SiemDestinationOut):
    """A destination just saved, with a new signing secret shown this once."""

    secret: str | None = Field(
        default=None, description="The new signing secret: shown once, never again."
    )


class SiemRotateIn(BaseModel):
    """Start a rotation (a new secret, both sign) or finish it (the previous one stops)."""

    model_config = ConfigDict(extra="forbid")

    finish: bool = False


class SiemTestOut(BaseModel):
    """What the test send found (labels: `siem_error.<code>`)."""

    result: Literal["delivered", "failed"]
    error_code: str | None


async def _out(
    session: TenantSession, row: SiemDestination, secret: str | None = None
) -> SiemDestinationMadeOut:
    found = {r.id: h for r, h in await siem.list_destinations(session)}
    health = found.get(row.id) or siem.health(row, 0)
    return SiemDestinationMadeOut(**SiemDestinationOut.of(row, health).model_dump(), secret=secret)


@router.get("/destinations", summary="Where audit and sign-in entries stream")
async def list_destinations(session: TenantSession, subject: Manage) -> list[SiemDestinationOut]:
    """By name, each with its health; never a secret."""
    del subject
    return [SiemDestinationOut.of(r, h) for r, h in await siem.list_destinations(session)]


@router.post(
    "/destinations",
    summary="Stream to a security monitoring system",
    status_code=status.HTTP_201_CREATED,
    response_model=SiemDestinationMadeOut,
    dependencies=[RecentAuth],
)
async def add_destination(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: SiemDestinationIn,
    request: Request,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    note: Annotated[
        AuditNote, audited("audit.siem_destination_added", object_type="siem_destination")
    ],
) -> Response:
    """Starts at the end of the chain (no history). A webhook's secret is in this answer once."""
    secret: list[str] = []  # only this request's own answer carries it

    async def run() -> Created:
        made = await siem.add_destination(session, subject, request.app.state.settings, body.data())
        note.object_id = str(made.row.id)
        note.details = {"kind": made.row.kind}
        if made.secret is not None:
            secret.append(made.secret)
        out = await _out(session, made.row)  # the stored answer (for replays) never holds it
        return Created(body=out.model_dump(mode="json"), headers={"ETag": f'"{made.row.version}"'})

    response = await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)
    answer: dict[str, Any] = json.loads(bytes(response.body))
    if secret:
        answer["secret"] = secret[0]
    headers = {k: v for k, v in response.headers.items() if k.lower() not in _SKIP} | NO_STORE
    return JSONResponse(answer, status_code=response.status_code, headers=headers)


_SKIP = frozenset({"content-length", "content-type"})


@router.patch(
    "/destinations/{destination_id}",
    summary="Change a destination",
    dependencies=[RecentAuth],
)
async def change_destination(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    destination_id: uuid.UUID,
    body: SiemDestinationIn,
    request: Request,
    response: Response,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    note: Annotated[
        AuditNote,
        audited(
            "audit.siem_destination_changed",
            object_type="siem_destination",
            object_param="destination_id",
        ),
    ],
) -> SiemDestinationOut:
    """Its cursors stay where they are; a fixed destination is tried at once."""
    row = await siem.change_destination(
        session,
        subject,
        request.app.state.settings,
        destination_id,
        body.data(),
        expected_version=version,
    )
    note.details = {"kind": row.kind, "enabled": row.enabled}
    set_etag(response, row.version)
    return await _out(session, row)


@router.post(
    "/destinations/{destination_id}/rotate-secret",
    summary="Rotate a webhook's signing secret",
    dependencies=[RecentAuth],
)
async def rotate_secret(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    destination_id: uuid.UUID,
    body: SiemRotateIn,
    request: Request,
    response: Response,
    session: TenantSession,
    subject: Manage,
    note: Annotated[
        AuditNote,
        audited(
            "audit.siem_secret_rotated",
            object_type="siem_destination",
            object_param="destination_id",
        ),
    ],
) -> SiemDestinationMadeOut:
    """Start: a new secret (in this answer once), both sign. Finish: the previous one stops."""
    made = await siem.rotate_secret(
        session,
        subject,
        request.app.state.settings,
        destination_id,
        finish=body.finish,
    )
    note.details = {"step": "finished" if body.finish else "started"}
    response.headers.update(NO_STORE)
    set_etag(response, made.row.version)
    return await _out(session, made.row, made.secret)


@router.post("/destinations/{destination_id}/test", summary="Send a test entry now")
async def test_destination(
    destination_id: uuid.UUID,
    request: Request,
    session: TenantSession,
    subject: Manage,
    note: Annotated[
        AuditNote,
        audited(
            "audit.siem_test_sent", object_type="siem_destination", object_param="destination_id"
        ),
    ],
) -> SiemTestOut:
    """One test entry, sent now; no cursor moves. The error is a code."""
    error = await siem.send_test(session, subject, request.app.state.settings, destination_id)
    note.details = {"result": error or "delivered"}
    return SiemTestOut(result="failed" if error else "delivered", error_code=error)


@router.delete(
    "/destinations/{destination_id}",
    summary="Stop streaming to a destination",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[RecentAuth],
)
async def remove_destination(
    destination_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    note: Annotated[
        AuditNote,
        audited(
            "audit.siem_destination_removed",
            object_type="siem_destination",
            object_param="destination_id",
        ),
    ],
) -> None:
    """Soft: nothing more is sent; the row and its audit stay."""
    del note  # the route's entry is enough: the object and the action
    await siem.remove_destination(session, subject, destination_id)
