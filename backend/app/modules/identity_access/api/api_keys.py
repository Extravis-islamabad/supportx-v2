"""API keys over HTTP (REQ-INT-019, 021; D-128).

Every route here is for the browser only (`require_signed_in` refuses keys), so a key never makes,
lists or revokes keys, whatever its scopes. Who may do what is decided by the service:
`api_keys.manage` for keys of service identities and every key; one's own keys when the tenant
allows people to make them (the settings live with the other sign-in settings, Admin > Security).
"""

import json
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.audit import RequestFacts
from app.modules.identity_access.api.access import Policy
from app.modules.identity_access.domain import api_keys as rules
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.infra.models import ApiKey
from app.modules.identity_access.service import api_keys
from app.modules.identity_access.service.directory import user_names
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.clock import system_clock

SignedIn = Annotated[Subject, Depends(require_signed_in())]

router = APIRouter(
    prefix="/api-keys",
    tags=["api-keys"],
    dependencies=[Depends(rate_limit("identity"))],
)

KeyStatus = Literal["active", "expired", "revoked"]


class ApiKeyOut(BaseModel):
    """A key as the screen shows it: never its secret, only its last four characters."""

    id: uuid.UUID
    name: str
    owner_id: uuid.UUID
    owner_name: str | None
    scopes: list[str]
    last_four: str
    expires_at: datetime | None
    ip_allowlist: list[str]
    last_used_at: datetime | None
    last_used_ip: str | None
    revoked_at: datetime | None
    created_at: datetime
    status: KeyStatus

    @classmethod
    def of(cls, row: ApiKey, owner_name: str | None, now: datetime) -> "ApiKeyOut":
        """From the row."""
        state: KeyStatus = (
            "revoked"
            if row.revoked_at is not None
            else "expired"
            if row.expires_at is not None and row.expires_at <= now
            else "active"
        )
        return cls(
            id=row.id,
            name=row.name,
            owner_id=row.owner_id,
            owner_name=owner_name,
            scopes=list(row.scopes),
            last_four=row.last_four,
            expires_at=row.expires_at,
            ip_allowlist=list(row.ip_allowlist),
            last_used_at=row.last_used_at,
            last_used_ip=row.last_used_ip,
            revoked_at=row.revoked_at,
            created_at=row.created_at,
            status=state,
        )


class ApiKeyCreatedOut(ApiKeyOut):
    """A new key, with the whole key text: shown this once and never again (REQ-INT-019 AC1)."""

    key: str | None = Field(
        description=(
            "The key: store it now, only its last four characters remain. Empty when this answer"
            " repeats an earlier one (same Idempotency-Key): the key is never stored, so revoke"
            " that key and make a new one if its text was lost."
        )
    )


class ApiKeyIn(BaseModel):
    """A new key."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=rules.NAME_MAX)
    owner_id: uuid.UUID | None = Field(
        default=None, description="A service identity (needs api_keys.manage); empty: yourself."
    )
    scopes: list[str] = Field(
        min_length=1, max_length=200, description="From GET /api-keys/scopes."
    )
    expires_at: datetime | None = Field(
        default=None, description="Empty: 90 days from now. At most a year ahead."
    )
    never_expires: bool = Field(
        default=False, description="Only when the tenant allows keys without expiry."
    )
    ip_allowlist: list[str] = Field(
        default_factory=list, max_length=rules.ALLOWLIST_MAX, description="Addresses or CIDRs."
    )


class ScopeOut(BaseModel):
    """A scope a key may carry: an area of the permission catalogue, read or write."""

    code: str
    area: str
    access: Literal["read", "write"]


def known_scopes(policy_keys: list[str]) -> list[str]:
    """Every scope of the catalogue, except the key screens' own area (never for a key)."""
    return [s for s in rules.scopes_for(policy_keys) if not s.startswith("api_keys:")]


@router.get("/scopes", summary="Scopes a key may carry")
async def list_scopes(subject: SignedIn, policy: Policy) -> list[ScopeOut]:
    """One read and one write scope per area of the permission catalogue."""
    del subject
    codes = known_scopes(list(policy.catalogue.permissions))
    return [
        ScopeOut(
            code=c, area=c.partition(":")[0], access="read" if c.endswith(":read") else "write"
        )
        for c in codes
    ]


async def _out(session: TenantSession, rows: list[ApiKey], now: datetime) -> list[ApiKeyOut]:
    names = await user_names(session, sorted({str(r.owner_id) for r in rows}))
    return [ApiKeyOut.of(r, names.get(str(r.owner_id)), now) for r in rows]


@router.get("", summary="API keys")
async def list_keys(session: TenantSession, subject: SignedIn) -> list[ApiKeyOut]:
    """Every key for api_keys.manage; your own keys for everyone else. Never a secret."""
    rows = await api_keys.list_keys(session, subject)
    return await _out(session, rows, system_clock.now())


@router.post(
    "",
    summary="Make an API key",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiKeyCreatedOut,
)
async def create_key(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: ApiKeyIn,
    request: Request,
    session: TenantSession,
    subject: SignedIn,
    policy: Policy,
    idempotency: Idempotency,
) -> Response:
    """Make a key; the answer carries its text this once.

    A retry with the same Idempotency-Key makes no second key and answers without the key text,
    which is never stored anywhere (D-128).
    """
    settings = request.app.state.settings
    secret: list[str] = []  # the text, only for this request's own answer

    async def go() -> Created:
        now = system_clock.now()
        made = await api_keys.create_key(
            session,
            subject,
            settings,
            RequestFacts.of(request),
            owner_id=body.owner_id,
            name=body.name,
            scopes=body.scopes,
            known_scopes=frozenset(known_scopes(list(policy.catalogue.permissions))),
            expires_at=body.expires_at,
            never_expires=body.never_expires,
            ip_allowlist=body.ip_allowlist,
            now=now,
        )
        names = await user_names(session, [str(made.row.owner_id)])
        secret.append(made.text)
        # The stored answer (for replays) never holds the key text.
        out = ApiKeyCreatedOut(
            **ApiKeyOut.of(made.row, names.get(str(made.row.owner_id)), now).model_dump(),
            key=None,
        )
        return Created(body=out.model_dump(mode="json"))

    response = await idempotency.run(body, go)
    if not secret:
        return response  # a replay: no key text
    answer = json.loads(bytes(response.body))
    answer["key"] = secret[0]
    return JSONResponse(answer, status_code=response.status_code, headers=_headers(response))


def _headers(response: Response) -> dict[str, str]:
    skip = {"content-length", "content-type"}
    return {k: v for k, v in response.headers.items() if k.lower() not in skip}


@router.post("/{key_id}/revoke", summary="Revoke an API key")
async def revoke_key(
    key_id: uuid.UUID, request: Request, session: TenantSession, subject: SignedIn
) -> ApiKeyOut:
    """At once: the key's next call is refused (REQ-INT-019 AC2). Revoking again changes nothing."""
    now = system_clock.now()
    row = await api_keys.revoke_key(session, subject, RequestFacts.of(request), key_id, now)
    return (await _out(session, [row], now))[0]
