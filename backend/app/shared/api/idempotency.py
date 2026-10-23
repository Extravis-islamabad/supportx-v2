"""Idempotency-Key on POST (architecture.md §6.5, §10; WP-008; ADR-020).

    POST /api/v1/things   Idempotency-Key: 7d1c...   {"title": "Printer jam"}
      first time      → runs, 201, response stored
      same key + body → the stored 201 again (header Idempotent-Replayed: true); nothing runs
      same key, other body or endpoint → 422 idempotency_key_reused

Keys are scoped to (tenant, user): another user's identical key is a different key, and nobody
can read anyone else's stored response. They live 24 hours (SUPPORTX_IDEMPOTENCY_TTL_HOURS).

The record is a row in `idempotency_keys`, claimed and filled inside the request's own
transaction, so it commits exactly when the business change does:

- crash or error before commit → claim and change roll back together; a retry runs normally;
- two identical requests at once → the second one's INSERT waits on the primary key until the
  first commits, then finds the stored response and replays it. Two records can never be created.

Usage (the endpoint keeps a typed response model for the OpenAPI document):

    @router.post("/things", status_code=201, response_model=ThingOut)
    async def create_thing(body: ThingIn, session: TenantSession, idempotency: Idempotency):
        return await idempotency.run(body, lambda: service.create(session, body), status_code=201)
"""

import hashlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import Integer, PrimaryKeyConstraint, String, literal_column, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import SESSION_TENANT_KEY, TenantSession
from app.core.errors import BadRequest, Conflict, ValidationFailed
from app.core.tenancy import TenantContext
from app.shared.db.models import Base, TenantScoped

IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
NO_USER = uuid.UUID(int=0)  # requests without a user (dev header, system) share this scope
_KEY = re.compile(r"^[\x21-\x7e]{1,255}$")  # visible ASCII: UUIDs, ULIDs, random tokens
# Response headers worth replaying; everything else is regenerated per response.
REPLAYED_HEADERS = ("location", "etag")


class IdempotencyRecord(TenantScoped, Base):
    """A POST that was (or is being) handled for one key."""

    __tablename__ = "idempotency_keys"

    user_id: Mapped[uuid.UUID]
    key: Mapped[str] = mapped_column(String(255))
    route: Mapped[str] = mapped_column(String(300))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[Any | None] = mapped_column(JSONB)  # Any: arbitrary JSON document
    response_headers: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime]
    expires_at: Mapped[datetime]

    __table_args__ = (PrimaryKeyConstraint("tenant_id", "user_id", "key"),)


@dataclass(frozen=True)
class Created:
    """What an idempotent operation returns: the body, plus headers such as Location."""

    body: BaseModel | Mapping[str, Any]
    headers: Mapping[str, str] = field(default_factory=dict)


def fingerprint(route: str, body: BaseModel | Mapping[str, Any] | None) -> str:
    """SHA-256 of the endpoint and the canonical JSON body (key order does not matter)."""
    document = jsonable_encoder(body) if body is not None else None
    canonical = json.dumps([route, document], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class IdempotencyGuard:
    """Per-request helper; see the module docstring."""

    def __init__(
        self, *, request: Request, session: AsyncSession, key: str | None, ttl: timedelta
    ) -> None:
        self.request = request
        self.session = session
        self.key = key
        self.ttl = ttl
        route = request.scope.get("route")
        self.route = f"{request.method} {getattr(route, 'path', request.url.path)}"

    async def run(
        self,
        body: BaseModel | Mapping[str, Any] | None,
        operation: Callable[[], Awaitable[Created | BaseModel]],
        *,
        status_code: int = 201,
    ) -> Response:
        """Run `operation` once per key; replay its stored response for repeats."""
        if self.key is None:
            return self._respond(await operation(), status_code)
        context = self.session.info.get(SESSION_TENANT_KEY)
        if not isinstance(context, TenantContext):  # pragma: no cover - TenantSession guarantees it
            raise TypeError
        user_id = context.user_id or NO_USER
        print_ = fingerprint(self.route, body)
        if not await self._claim(context.tenant_id, user_id, print_):
            return await self._replay(context.tenant_id, user_id, print_)
        response = self._respond(await operation(), status_code)
        await self._store(context.tenant_id, user_id, response)
        return response

    async def _claim(self, tenant_id: uuid.UUID, user_id: uuid.UUID, print_: str) -> bool:
        """True if this request owns the key now (new, or the old record had expired)."""
        now = datetime.now(UTC)
        values = {
            "route": self.route,
            "fingerprint": print_,
            "status_code": None,
            "response_body": None,
            "response_headers": None,
            "created_at": now,
            "expires_at": now + self.ttl,
        }
        statement = (
            insert(IdempotencyRecord)
            .values(tenant_id=tenant_id, user_id=user_id, key=self.key, **values)
            .on_conflict_do_update(
                index_elements=["tenant_id", "user_id", "key"],
                set_=values,
                where=IdempotencyRecord.expires_at <= now,
            )
            .returning(literal_column("1", Integer))
        )
        return (await self.session.execute(statement)).first() is not None

    async def _replay(self, tenant_id: uuid.UUID, user_id: uuid.UUID, print_: str) -> Response:
        record = await self.session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == tenant_id,
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.key == self.key,
            )
        )
        if record is None or record.status_code is None:
            # Only possible within one transaction (the same request twice); never across them.
            raise Conflict(code="idempotency_request_in_progress", headers={"Retry-After": "1"})
        if record.fingerprint != print_ or record.route != self.route:
            raise ValidationFailed(code="idempotency_key_reused")
        headers = {**(record.response_headers or {}), REPLAYED_HEADER: "true"}
        return JSONResponse(record.response_body, status_code=record.status_code, headers=headers)

    async def _store(self, tenant_id: uuid.UUID, user_id: uuid.UUID, response: Response) -> None:
        record = await self.session.get(IdempotencyRecord, (tenant_id, user_id, self.key))
        if record is None:  # pragma: no cover - claimed a moment ago in this transaction
            raise RuntimeError
        record.status_code = response.status_code
        record.response_body = json.loads(bytes(response.body))
        record.response_headers = {
            name: value for name, value in response.headers.items() if name in REPLAYED_HEADERS
        }
        await self.session.flush()

    @staticmethod
    def _respond(result: Created | BaseModel, status_code: int) -> JSONResponse:
        created = result if isinstance(result, Created) else Created(result)
        return JSONResponse(
            jsonable_encoder(created.body), status_code=status_code, headers=dict(created.headers)
        )


def idempotency_key(
    value: Annotated[
        str | None,
        Header(
            alias=IDEMPOTENCY_HEADER,
            description="Optional. A unique key per intended create; retries reuse it.",
        ),
    ] = None,
) -> str | None:
    """The validated Idempotency-Key header, if sent."""
    if value is None:
        return None
    if not _KEY.fullmatch(value):
        raise BadRequest(code="invalid_idempotency_key")
    return value


def get_idempotency(
    request: Request,
    session: TenantSession,
    key: Annotated[str | None, Depends(idempotency_key)],
) -> IdempotencyGuard:
    """FastAPI dependency (shares the request's TenantSession, hence its transaction)."""
    hours = request.app.state.settings.idempotency_ttl_hours
    return IdempotencyGuard(request=request, session=session, key=key, ttl=timedelta(hours=hours))


Idempotency = Annotated[IdempotencyGuard, Depends(get_idempotency)]
