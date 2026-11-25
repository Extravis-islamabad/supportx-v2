"""MonetX connections (WP-053 S6; REQ-INT-040): set up, test, change and remove.

- `monitoring.manage` (the coordinator's Q2: this module's own right) and the licence feature
  `monetx_integration`, checked on the server (rule f).
- The API token goes to integrations' secrets store; this module keeps only the reference, and
  no answer ever carries the token (`has_secret` says whether one is set).
- Changes take If-Match; every change is audited by the route and emits `ConnectionChanged`.
- A connection test is one read (GET). Its failure is a labelled reason, e.g.
  `monitoring_not_reachable_from_saas` for a private MonetX that SaaS can't reach yet (D-172).
"""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.modules import integrations, licensing
from app.modules.licensing import Feature
from app.modules.monitoring_integrations.domain.monitoring import NO_SECRET
from app.modules.monitoring_integrations.events import ConnectionChange, ConnectionChanged
from app.modules.monitoring_integrations.infra.models import MonitoringConnection
from app.modules.monitoring_integrations.infra.monetx_client import (
    EgressTransport,
    MonetXClient,
    MonetXTransport,
    MonitoringUnavailableError,
)
from app.shared.connectors.ports import SecretType
from app.shared.db.repository import Repository
from app.shared.egress import installation_allowance
from app.shared.events import record_event

MANAGE = "monitoring.manage"
FEATURE = Feature.MONETX_INTEGRATION
OWNER_KIND = "monitoring_connection"
TOKEN_ROLE = "api_token"  # noqa: S105 - a role code
NAME_MAX, URL_MAX, TOKEN_MAX, SITE_MAP_MAX = 120, 500, 4000, 500

TransportFactory = Callable[[MonitoringConnection, str, Settings], MonetXTransport]


def _egress(row: MonitoringConnection, token: str, settings: Settings) -> MonetXTransport:
    return EgressTransport(
        base_url=row.base_url,
        token=token,
        allowance=installation_allowance(settings),
        tenant_id=row.tenant_id,
    )


_FACTORY: list[TransportFactory] = [_egress]


def set_transport_factory(factory: TransportFactory | None) -> None:
    """Tests only: a stand-in MonetX (tests/monetx_fake.py); None restores egress."""
    _FACTORY[:] = [factory or _egress]


class ConnectionRepository(Repository[MonitoringConnection]):
    """Connections of the session's tenant."""

    model = MonitoringConnection


@dataclass(frozen=True)
class ConnectionView:
    """A connection as the API shows it: never the token."""

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
    def of(cls, row: MonitoringConnection) -> "ConnectionView":
        """The view of a row."""
        return cls(
            id=row.id,
            name=row.name,
            base_url=row.base_url,
            enabled=row.enabled,
            has_secret=row.secret_ref is not None,
            site_map={str(k): str(v) for k, v in (row.site_map or {}).items()},
            last_run_at=row.last_run_at,
            last_error_code=row.last_error_code,
            version=row.version,
        )


def _tenant(session: AsyncSession) -> uuid.UUID:
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant


def _problem(field: str, code: str) -> FieldError:
    return FieldError(field=f"body.{field}", code=code, message_key=f"errors.field.{code}")


def _url_ok(url: str) -> bool:
    parts = urlsplit(url)
    return (
        len(url) <= URL_MAX
        and parts.scheme in {"https", "http"}
        and bool(parts.hostname)
        and not (parts.username or parts.password or parts.query or parts.fragment)
    )


def _site_map(raw: object) -> dict[str, str] | None:
    """The admin's group → site map with site IDs as UUIDs, or None when it isn't one."""
    if not isinstance(raw, Mapping) or len(raw) > SITE_MAP_MAX:
        return None
    site_map: dict[str, str] = {}
    for group, site in raw.items():
        try:
            site_map[str(group)[:200]] = str(uuid.UUID(str(site)))
        except ValueError:
            return None
    return site_map


def _checked(values: Mapping[str, Any]) -> dict[str, Any]:
    """The fields to store, or 422 with every problem (codes only)."""
    problems: list[FieldError] = []
    out: dict[str, Any] = {}
    if "name" in values:
        out["name"] = str(values["name"] or "").strip()
        if not 1 <= len(out["name"]) <= NAME_MAX:
            problems.append(_problem("name", "invalid_value"))
    if "base_url" in values:
        out["base_url"] = str(values["base_url"] or "").strip().rstrip("/")
        if not _url_ok(out["base_url"]):
            problems.append(_problem("base_url", "monitoring_base_url_invalid"))
    if "site_map" in values:
        site_map = _site_map(values["site_map"] or {})
        if site_map is None:
            problems.append(_problem("site_map", "invalid_value"))
        else:
            out["site_map"] = site_map
    if "enabled" in values:
        out["enabled"] = bool(values["enabled"])
    if problems:
        raise ValidationFailed(errors=problems)
    return out


async def _name_taken(session: AsyncSession, name: str, other: uuid.UUID | None) -> bool:
    query = select(MonitoringConnection.id).where(
        func.lower(MonitoringConnection.name) == name.lower(),
        MonitoringConnection.deleted_at.is_(None),
    )
    if other is not None:
        query = query.where(MonitoringConnection.id != other)
    return await session.scalar(query.limit(1)) is not None


def _check_token(token: str | None) -> str | None:
    if token is None:
        return None
    value = token.strip()
    if not 1 <= len(value) <= TOKEN_MAX:
        raise ValidationFailed(errors=[_problem("token", "invalid_value")])
    return value


async def list_connections(session: AsyncSession) -> list[ConnectionView]:
    """The tenant's connections, oldest first."""
    rows = await session.scalars(
        select(MonitoringConnection)
        .where(MonitoringConnection.deleted_at.is_(None))
        .order_by(MonitoringConnection.created_at, MonitoringConnection.id)
    )
    return [ConnectionView.of(r) for r in rows]


async def get_connection(session: AsyncSession, connection_id: uuid.UUID) -> ConnectionView:
    """One connection (404 when gone)."""
    return ConnectionView.of(await ConnectionRepository(session).get(connection_id))


async def create_connection(
    session: AsyncSession, settings: Settings, values: Mapping[str, Any], *, token: str | None
) -> ConnectionView:
    """A new connection (the plan must include MonetX)."""
    await licensing.require_feature(_tenant(session), FEATURE)
    fields = _checked({"enabled": True, "site_map": {}, **values})
    if "name" not in fields or "base_url" not in fields:
        missing = [f for f in ("name", "base_url") if f not in fields]
        raise ValidationFailed(errors=[_problem(f, "required") for f in missing])
    if await _name_taken(session, fields["name"], None):
        raise Conflict(code="monitoring_connection_name_taken")
    row = await ConnectionRepository(session).add(MonitoringConnection(**fields))
    secret = _check_token(token)
    if secret is not None:
        row.secret_ref = await integrations.store_connector_secret(
            session,
            settings,
            owner_kind=OWNER_KIND,
            owner_id=row.id,
            role=TOKEN_ROLE,
            secret_type=SecretType.API_TOKEN.value,
            value=secret,
        )
        await session.flush()
    await _event(session, row, "added")
    return ConnectionView.of(row)


async def update_connection(  # noqa: PLR0913 - the row, its changes, the token and the version
    session: AsyncSession,
    settings: Settings,
    connection_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    token: str | None,
    expected_version: int,
) -> ConnectionView:
    """Change a connection; a new token replaces the old one (rotated, same reference)."""
    await licensing.require_feature(_tenant(session), FEATURE)
    fields = _checked(values)
    if "name" in fields and await _name_taken(session, fields["name"], connection_id):
        raise Conflict(code="monitoring_connection_name_taken")
    repository = ConnectionRepository(session)
    row = await repository.update(connection_id, expected_version=expected_version, changes=fields)
    secret = _check_token(token)
    if secret is not None:
        row.secret_ref = await integrations.store_connector_secret(
            session,
            settings,
            owner_kind=OWNER_KIND,
            owner_id=row.id,
            role=TOKEN_ROLE,
            secret_type=SecretType.API_TOKEN.value,
            value=secret,
        )
        await session.flush()
    await _event(session, row, "changed")
    return ConnectionView.of(row)


async def remove_connection(
    session: AsyncSession, connection_id: uuid.UUID, *, expected_version: int
) -> None:
    """Remove a connection; its token is forgotten. Its devices' CIs stay (never deleted)."""
    row = await ConnectionRepository(session).soft_delete(
        connection_id, expected_version=expected_version
    )
    await integrations.forget_connector_secrets(session, owner_kind=OWNER_KIND, owner_id=row.id)
    await _event(session, row, "removed")


async def _event(
    session: AsyncSession, row: MonitoringConnection, change: ConnectionChange
) -> None:
    await record_event(
        session,
        ConnectionChanged(connection_id=row.id, change=change, version=row.version),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def client_for(
    session: AsyncSession, settings: Settings, row: MonitoringConnection
) -> MonetXClient:
    """The connection's client, or `MonitoringUnavailableError(NO_SECRET)` without a token."""
    token = await integrations.read_connector_secret(session, settings, row.secret_ref)
    if token is None:
        raise MonitoringUnavailableError(NO_SECRET)
    return MonetXClient(_FACTORY[0](row, token, settings))


async def test_connection(
    session: AsyncSession, settings: Settings, connection_id: uuid.UUID
) -> str | None:
    """One read; None when it works, else the labelled reason (also kept on the connection)."""
    await licensing.require_feature(_tenant(session), FEATURE)
    row = await session.scalar(
        select(MonitoringConnection).where(
            MonitoringConnection.id == connection_id, MonitoringConnection.deleted_at.is_(None)
        )
    )
    if row is None:
        raise NotFound(code="monitoring_connection_not_found")
    try:
        await (await client_for(session, settings, row)).check()
    except MonitoringUnavailableError as error:
        row.last_error_code = error.code
        await session.flush()
        return error.code
    row.last_error_code = None
    await session.flush()
    return None
