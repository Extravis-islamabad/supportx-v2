"""Streaming audit and sign-in entries to a security monitoring system (REQ-AUD-011, WP-057 S5a).

- **Destinations** (at most 5 a tenant): syslog over TCP with TLS (CEF or JSON, RFC 5424 framed
  by RFC 6587), or an HTTPS webhook (a JSON batch, signed with app/shared/crypto/signing.py).
  Plain syslog is not offered (the coordinator, S5 Q4). Adding, changing, testing, rotating and
  removing need `audit.manage` (the routes) and the `siem_stream` feature (adding and changing),
  and each is audited by its route with codes only.
- **What is sent:** an audit entry's chain content (never `audit_personal`, never the salted
  commitments), with its own ID and its chain `seq` so the receiver can drop a duplicate; a
  sign-in's facts by user ID (identity's `sign_ins_after`: no IP, device or name).
- **Delivery** runs only in the schedule (`deliver_tenant`), never in a request: from each
  stream's cursor, in order, at most `BATCH_MAX` at a time. The cursor moves only after the
  destination took the batch (an HTTP 2xx; the TLS stream written and flushed). A failure keeps
  the cursor and backs off (5 s doubling to 5 min): nothing is skipped, an outage resumes where it
  stopped (at least once). A lapsed licence pauses delivery and keeps the cursor (condition 4).
- **Secrets** (the webhook's signing secret, a CA bundle, a client certificate and key) are
  sealed with the field cipher, bound to the row. A signing secret is shown once when made; a
  rotation keeps the previous one signing too until it is finished. Nothing is read back.
"""

import asyncio
import secrets
import ssl
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.audit.domain import siem
from app.modules.audit.domain.integrity import entry_content, format_time
from app.modules.audit.infra.models import AuditChainLink, SiemDestination
from app.modules.audit.service.integrity import entries_of
from app.modules.audit.service.recording import WORKER, record
from app.modules.licensing import Feature, has_feature, require_feature
from app.shared.clock import system_clock
from app.shared.crypto.signing import sign
from app.shared.egress import (
    Destination,
    EgressError,
    OutboundRequest,
    installation_allowance,
    send,
    tls_context,
)
from app.shared.egress.sockets import pinned_address
from app.shared.fields import Binding, FieldKeysUnavailable, field_cipher_for, purpose
from app.shared.history import stale_version
from app.shared.ids import new_id

log = get_logger(__name__)


class Actor(Protocol):
    """Who acts (identity's Subject fits): audit never imports identity_access (a cycle)."""

    @property
    def tenant_id(self) -> uuid.UUID:
        """Their tenant."""
        ...

    @property
    def user_id(self) -> uuid.UUID:
        """Who they are."""
        ...


@dataclass(frozen=True)
class SignInRow:
    """One sign-in as identity hands it over: no IP, device, name or e-mail address."""

    id: uuid.UUID
    occurred_at: datetime
    user_id: uuid.UUID | None
    outcome: str
    reason: str | None
    method: str
    app: str


SignInsAfter = Callable[
    [AsyncSession, tuple[datetime, uuid.UUID] | None, int], Awaitable[Sequence[SignInRow]]
]
LatestSignIn = Callable[[AsyncSession], Awaitable[tuple[datetime, uuid.UUID] | None]]
_SIGN_INS: dict[str, Any] = {}


def register_sign_in_source(after: SignInsAfter, latest: LatestSignIn) -> None:
    """identity_access hands its sign-ins over (at import, like the other ports)."""
    _SIGN_INS["after"], _SIGN_INS["latest"] = after, latest


async def _sign_ins_after(
    session: AsyncSession, after: tuple[datetime, uuid.UUID] | None, limit: int
) -> Sequence[SignInRow]:
    reader: SignInsAfter | None = _SIGN_INS.get("after")
    return [] if reader is None else await reader(session, after, limit)


async def _latest_sign_in(session: AsyncSession) -> tuple[datetime, uuid.UUID] | None:
    reader: LatestSignIn | None = _SIGN_INS.get("latest")
    return None if reader is None else await reader(session)


TABLE = "siem_destinations"
SECRET = purpose("audit", "siem_secret")
CA_PEM = purpose("audit", "siem_ca")
CLIENT_CERT = purpose("audit", "siem_client_cert")
CLIENT_KEY = purpose("audit", "siem_client_key")

# The TLS syslog ports a destination may use (RFC 5425's 6514, and the two SIEMs often take).
SYSLOG_PORTS = frozenset({6514, 1514, 10514})
# Plain syslog (D-181, an admin's opt-in): the usual ports, still through the egress allowance.
PLAIN_SYSLOG_PORTS = frozenset({514, 1514, 10514})
SEND_TIMEOUT = 10.0
BACKOFF_FIRST = timedelta(seconds=5)
BACKOFF_MAX = timedelta(minutes=5)
VERSION = "2"

# Health codes (`siem_error.<code>`): never a message from the far end, which could hold anything.
NOT_ENTITLED = "not_entitled"
UNREACHABLE = "unreachable"
REFUSED = "refused"
TLS = "tls"
NOT_ALLOWED = "address_not_allowed"
TIMEOUT = "timeout"
KEYS = "keys_unavailable"
FAILED = "failed"


@dataclass(frozen=True)
class DestinationInput:
    """What an admin sets; a PEM is None when unchanged, "" to clear it."""

    name: str
    kind: siem.SiemKind
    format: siem.SiemFormat = siem.SiemFormat.JSON
    host: str | None = None
    port: int | None = None
    url: str | None = None
    streams: tuple[siem.SiemStream, ...] = (siem.SiemStream.AUDIT,)
    enabled: bool = True
    ca_pem: str | None = None
    client_cert_pem: str | None = None
    client_key_pem: str | None = None
    # D-181: plain TCP or UDP only by an admin's deliberate choice (syslog only).
    transport: siem.SiemTransport = siem.SiemTransport.TLS
    udp_max_bytes: int = siem.UDP_MAX_DEFAULT


@dataclass(frozen=True)
class Health:
    """How a destination is doing: behind by N audit entries, the last error as a code."""

    behind: int
    last_success_at: datetime | None
    last_error_code: str | None
    last_error_at: datetime | None
    failing_since: datetime | None


@dataclass(frozen=True)
class Made:
    """A destination saved, and its new signing secret (shown once: never stored in clear)."""

    row: SiemDestination
    secret: str | None = None


@dataclass
class _Batch:
    """What one delivery attempt sends and how far it moves each cursor."""

    lines: list[str] = field(default_factory=list)
    objects: list[dict[str, Any]] = field(default_factory=list)
    last_seq: int | None = None
    last_sign_in: tuple[datetime, uuid.UUID] | None = None


def _invalid(*problems: tuple[str, str]) -> ValidationFailed:
    return ValidationFailed(
        errors=[
            FieldError(field=f"body.{name}", code=code, message_key=f"errors.field.{code}")
            for name, code in problems
        ]
    )


def _syslog_problems(data: DestinationInput) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    if not (data.host or "").strip():
        problems.append(("host", "required"))
    tls = data.transport is siem.SiemTransport.TLS
    if data.port not in (SYSLOG_PORTS if tls else PLAIN_SYSLOG_PORTS):
        problems.append(("port", "siem_port_not_allowed"))
    if not siem.UDP_MAX_LOWEST <= data.udp_max_bytes <= siem.UDP_MAX_HIGHEST:
        problems.append(("udp_max_bytes", "out_of_range"))
    return problems


def _webhook_problems(data: DestinationInput) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    parts = urlsplit(data.url or "")
    if parts.scheme != "https" or not parts.hostname:
        problems.append(("url", "https_required"))
    if data.format is not siem.SiemFormat.JSON:
        problems.append(("format", "siem_webhook_json_only"))
    if data.transport is not siem.SiemTransport.TLS:  # D-181: a webhook is HTTPS, always
        problems.append(("transport", "siem_webhook_https_only"))
    return problems


def _checked(data: DestinationInput) -> None:
    problems: list[tuple[str, str]] = []
    if not data.name.strip():
        problems.append(("name", "required"))
    if not data.streams:
        problems.append(("streams", "required"))
    problems += (
        _syslog_problems(data) if data.kind is siem.SiemKind.SYSLOG else _webhook_problems(data)
    )
    if bool(data.client_cert_pem) != bool(data.client_key_pem) and (
        data.client_cert_pem is not None and data.client_key_pem is not None
    ):
        problems.append(("client_key_pem", "siem_cert_and_key_together"))
    if problems:
        raise _invalid(*problems)


async def _name_free(session: AsyncSession, name: str, other_than: uuid.UUID | None = None) -> None:
    """Names are unique per tenant (case-insensitive): a clash is a labelled 409, never a 500."""
    query = select(SiemDestination.id).where(
        SiemDestination.deleted_at.is_(None),
        func.lower(SiemDestination.name) == name.strip().lower(),
    )
    if other_than is not None:
        query = query.where(SiemDestination.id != other_than)
    if await session.scalar(query.limit(1)) is not None:
        raise Conflict(code="siem_destination_name_taken")


async def _chain_end(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.coalesce(func.max(AuditChainLink.seq), 0))) or 0)


async def _seal(
    session: AsyncSession, settings: Settings, row: SiemDestination, what: str, value: str
) -> str:
    cipher = field_cipher_for(session, settings)
    return await cipher.seal(what, Binding(TABLE, row.id, what), value)


async def _open(
    session: AsyncSession, settings: Settings, row: SiemDestination, what: str, text: str | None
) -> str | None:
    if not text:
        return None
    cipher = field_cipher_for(session, settings)
    return await cipher.open(what, Binding(TABLE, row.id, what), text)


def _pems_usable(data: DestinationInput) -> None:
    ca = data.ca_pem or None
    cert, key = data.client_cert_pem or None, data.client_key_pem or None
    problems: list[tuple[str, str]] = []
    if ca is not None:
        try:
            ssl.create_default_context(cadata=ca)
        except (ssl.SSLError, ValueError):
            problems.append(("ca_pem", "siem_pem_invalid"))
    if cert is not None and key is not None:
        try:
            tls_context(Destination(client_cert_pem=cert, client_key_pem=key))
        except (EgressError, ssl.SSLError, ValueError):
            problems.append(("client_cert_pem", "siem_pem_invalid"))
    if problems:
        raise _invalid(*problems)


async def _apply_pems(
    session: AsyncSession, settings: Settings, row: SiemDestination, data: DestinationInput
) -> None:
    """Seal the TLS material given; "" clears it, None leaves it as it was.

    Each PEM is loaded into a throwaway TLS context first: one that can't be used is refused at
    the field (422 `siem_pem_invalid`), never saved and never echoed (lane B, #564 (2)).
    """
    _pems_usable(data)
    for value, what, column in (
        (data.ca_pem, CA_PEM, "ca_pem_sealed"),
        (data.client_cert_pem, CLIENT_CERT, "client_cert_sealed"),
        (data.client_key_pem, CLIENT_KEY, "client_key_sealed"),
    ):
        if value is None:
            continue
        setattr(row, column, await _seal(session, settings, row, what, value) if value else None)


async def list_destinations(session: AsyncSession) -> list[tuple[SiemDestination, Health]]:
    """The tenant's live destinations, by name, each with its health."""
    end = await _chain_end(session)
    rows = await session.scalars(
        select(SiemDestination)
        .where(SiemDestination.deleted_at.is_(None))
        .order_by(func.lower(SiemDestination.name))
    )
    return [(row, health(row, end)) for row in rows]


def health(row: SiemDestination, chain_end: int) -> Health:
    """How far behind a destination is and its last error (codes only)."""
    behind = max(chain_end - row.audit_seq_sent, 0) if siem.SiemStream.AUDIT in row.streams else 0
    return Health(
        behind, row.last_success_at, row.last_error_code, row.last_error_at, row.failing_since
    )


async def _live(session: AsyncSession, destination_id: uuid.UUID) -> SiemDestination:
    row = await session.scalar(
        select(SiemDestination)
        .where(SiemDestination.id == destination_id, SiemDestination.deleted_at.is_(None))
        .with_for_update()
    )
    if row is None:
        raise NotFound(code="siem_destination_not_found")
    return row


async def get_destination(session: AsyncSession, destination_id: uuid.UUID) -> SiemDestination:
    """One live destination of the tenant (locked for the change that follows), or 404."""
    return await _live(session, destination_id)


async def add_destination(
    session: AsyncSession,
    subject: Actor,
    settings: Settings,
    data: DestinationInput,
) -> Made:
    """A new destination, starting at the end of the chain and the newest sign-in (no history)."""
    await require_feature(subject.tenant_id, Feature.SIEM_STREAM)
    _checked(data)
    count = await session.scalar(select(func.count()).where(SiemDestination.deleted_at.is_(None)))
    if (count or 0) >= siem.DESTINATIONS_MAX:
        raise Conflict(code="siem_destinations_limit", params={"max": siem.DESTINATIONS_MAX})
    await _name_free(session, data.name)
    after = await _latest_sign_in(session)
    row = SiemDestination(
        id=new_id(),  # known before sealing: each secret is bound to its row (a tampered one fails)
        tenant_id=subject.tenant_id,
        name=data.name.strip(),
        kind=data.kind.value,
        format=data.format.value,
        host=(data.host or "").strip() or None if data.kind is siem.SiemKind.SYSLOG else None,
        port=data.port if data.kind is siem.SiemKind.SYSLOG else None,
        url=data.url if data.kind is siem.SiemKind.WEBHOOK else None,
        transport=data.transport.value,
        udp_max_bytes=data.udp_max_bytes,
        streams=[s.value for s in data.streams],
        enabled=data.enabled,
        audit_seq_sent=await _chain_end(session),
        sign_in_after_at=None if after is None else after[0],
        sign_in_after_id=None if after is None else after[1],
        created_by=subject.user_id,
        updated_by=subject.user_id,
    )
    secret: str | None = None
    if data.kind is siem.SiemKind.WEBHOOK:
        secret = secrets.token_urlsafe(32)
        row.secret_sealed = await _seal(session, settings, row, SECRET, secret)
    await _apply_pems(session, settings, row, data)
    session.add(row)
    await session.flush()
    return Made(row, secret)


async def change_destination(  # noqa: PLR0913 - the change, its version and who, explicit
    session: AsyncSession,
    subject: Actor,
    settings: Settings,
    destination_id: uuid.UUID,
    data: DestinationInput,
    *,
    expected_version: int,
) -> SiemDestination:
    """Change a destination (If-Match); its cursors stay where they are."""
    await require_feature(subject.tenant_id, Feature.SIEM_STREAM)
    row = await _live(session, destination_id)
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=TABLE, record_id=row.id
        )
    if data.kind.value != row.kind:
        raise _invalid(("kind", "siem_kind_fixed"))
    _checked(data)
    await _name_free(session, data.name, other_than=row.id)
    row.name = data.name.strip()
    row.format = data.format.value
    if row.kind == siem.SiemKind.SYSLOG:
        row.host, row.port = (data.host or "").strip(), data.port
        row.transport, row.udp_max_bytes = data.transport.value, data.udp_max_bytes
    else:
        row.url = data.url
    row.streams = [s.value for s in data.streams]
    row.enabled = data.enabled
    await _apply_pems(session, settings, row, data)
    row.next_attempt_at = None  # a fixed destination is tried at once
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    return row


async def rotate_secret(  # noqa: PLR0913 - the destination, the step, its version, who
    session: AsyncSession,
    subject: Actor,
    settings: Settings,
    destination_id: uuid.UUID,
    *,
    finish: bool,
    expected_version: int,
) -> Made:
    """Start a rotation (a new secret, both signing) or finish it (the previous one dropped).

    If-Match; a second start while one is unfinished is refused (409 `siem_rotation_open`):
    it would drop the secret receivers still use (lane B (3)).
    """
    row = await _live(session, destination_id)
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=TABLE, record_id=row.id
        )
    if row.kind != siem.SiemKind.WEBHOOK:
        raise _invalid(("kind", "siem_secret_webhook_only"))
    if not finish and row.previous_secret_sealed is not None:
        raise Conflict(code="siem_rotation_open")
    secret: str | None = None
    if finish:
        row.previous_secret_sealed = None
    else:
        old = await _open(session, settings, row, SECRET, row.secret_sealed)
        if old is not None:
            row.previous_secret_sealed = await _seal(session, settings, row, SECRET, old)
        secret = secrets.token_urlsafe(32)
        row.secret_sealed = await _seal(session, settings, row, SECRET, secret)
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    return Made(row, secret)


async def remove_destination(
    session: AsyncSession, subject: Actor, destination_id: uuid.UUID
) -> None:
    """Remove a destination (soft): nothing more is sent to it."""
    row = await _live(session, destination_id)
    row.deleted_at = system_clock.now()
    row.enabled = False
    row.updated_by = subject.user_id
    row.version += 1
    await session.flush()


# --- sending ------------------------------------------------------------------------------------


async def _tls(
    session: AsyncSession, settings: Settings, row: SiemDestination
) -> Destination | None:
    ca = await _open(session, settings, row, CA_PEM, row.ca_pem_sealed)
    cert = await _open(session, settings, row, CLIENT_CERT, row.client_cert_sealed)
    key = await _open(session, settings, row, CLIENT_KEY, row.client_key_sealed)
    if not (ca or cert or key):
        return None
    return Destination(ca_pem=ca, client_cert_pem=cert, client_key_pem=key)


async def _signing_secrets(
    session: AsyncSession, settings: Settings, row: SiemDestination
) -> list[bytes]:
    found: list[bytes] = []
    for text in (row.secret_sealed, row.previous_secret_sealed):
        value = await _open(session, settings, row, SECRET, text)
        if value is not None:
            found.append(value.encode())
    if not found:
        raise EgressError(KEYS)
    return found


async def _send_webhook(
    session: AsyncSession,
    settings: Settings,
    row: SiemDestination,
    objects: Sequence[dict[str, Any]],
    tenant_id: uuid.UUID,
) -> None:
    import json  # noqa: PLC0415 - only this path builds a batch

    body = json.dumps(
        {"entries": list(objects)}, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    signed = sign(
        await _signing_secrets(session, settings, row), int(system_clock.now().timestamp()), body
    )
    await send(
        OutboundRequest(
            method="POST",
            url=row.url or "",
            headers={"Content-Type": "application/json"},
            secret_headers=signed,
            body=body,
        ),
        allowance=installation_allowance(settings),
        module="audit",
        tenant_id=tenant_id,
        destination=await _tls(session, settings, row),
    )


async def _send_syslog(
    session: AsyncSession, settings: Settings, row: SiemDestination, lines: Sequence[str]
) -> None:
    host, port = row.host or "", row.port or 0
    transport = siem.SiemTransport(row.transport)
    allowed = SYSLOG_PORTS if transport is siem.SiemTransport.TLS else PLAIN_SYSLOG_PORTS
    if port not in allowed:
        raise EgressError(NOT_ALLOWED)
    ip = await pinned_address(host, port, installation_allowance(settings))
    at = system_clock.now()
    # HOSTNAME is the sender (RFC 5424 §6.2.4), never the receiver (lane B (4)).
    messages = [siem.syslog_line(line, hostname=siem.APP_NAME, at=at) for line in lines]
    if transport is siem.SiemTransport.UDP:
        await _send_udp(session, row, str(ip), port, messages)
        return
    context = (
        tls_context(await _tls(session, settings, row))
        if transport is siem.SiemTransport.TLS
        else None
    )
    payload = b"".join(siem.frame(message) for message in messages)
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                str(ip), port, ssl=context, server_hostname=host if context else None
            ),
            SEND_TIMEOUT,
        )
    except TimeoutError:
        raise EgressError(TIMEOUT) from None
    except OSError as exc:
        raise EgressError(TLS if "SSL" in type(exc).__name__ else UNREACHABLE) from None
    del reader
    try:
        writer.write(payload)
        await asyncio.wait_for(writer.drain(), SEND_TIMEOUT)
    except (TimeoutError, OSError):
        raise EgressError(UNREACHABLE) from None
    finally:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), SEND_TIMEOUT)
        except (TimeoutError, OSError):
            log.info("siem_close_unclean", destination_id=str(row.id))


class _Datagrams(asyncio.DatagramProtocol):
    """Sends and forgets: UDP has no acknowledgement (the status says "sent, not confirmed")."""


async def _send_udp(
    session: AsyncSession, row: SiemDestination, ip: str, port: int, messages: Sequence[str]
) -> None:
    """One RFC 5426 datagram per entry, never silently cut (D-181).

    A cut one is marked, and the audit log records how many were cut for this destination.
    """
    loop = asyncio.get_running_loop()
    try:
        transport, _ = await asyncio.wait_for(
            loop.create_datagram_endpoint(_Datagrams, remote_addr=(ip, port)), SEND_TIMEOUT
        )
    except (TimeoutError, OSError):
        raise EgressError(UNREACHABLE) from None
    cut = 0
    try:
        for message in messages:
            data, truncated = siem.datagram(message, row.udp_max_bytes)
            cut += truncated
            transport.sendto(data)
    except OSError:
        raise EgressError(UNREACHABLE) from None
    finally:
        transport.close()
    if cut:
        await record(
            session,
            action_code="audit.siem_entries_truncated",
            facts=WORKER,
            object_type="siem_destination",
            object_id=row.id,
            details={"entries": cut, "limit_bytes": row.udp_max_bytes},
        )


async def _batch(session: AsyncSession, row: SiemDestination) -> _Batch:
    """The next entries from each stream's cursor, in order (at most BATCH_MAX in all)."""
    found = _Batch()
    fmt = siem.SiemFormat(row.format)
    if siem.SiemStream.AUDIT in row.streams:
        links = list(
            await session.scalars(
                select(AuditChainLink)
                .where(AuditChainLink.seq > row.audit_seq_sent)
                .order_by(AuditChainLink.seq)
                .limit(siem.BATCH_MAX)
            )
        )
        if links:
            entries = {
                r["id"]: dict(r) for r in (await session.execute(entries_of(links))).mappings()
            }
            for link in links:
                entry = entries.get(link.entry_id)
                if entry is None:
                    continue  # archived away: the receiver gets the next one (seq shows the gap)
                content = {**entry_content(entry), "seq": link.seq}
                if isinstance(content.get("occurred_at"), datetime):
                    content["occurred_at"] = format_time(content["occurred_at"])
                found.objects.append(siem.payload(siem.SiemStream.AUDIT, content))
                found.lines.append(siem.body(siem.SiemStream.AUDIT, content, fmt, version=VERSION))
            found.last_seq = links[-1].seq
    room = siem.BATCH_MAX - len(found.objects)
    if siem.SiemStream.SIGN_INS in row.streams and room > 0:
        after = (
            None
            if row.sign_in_after_at is None or row.sign_in_after_id is None
            else (row.sign_in_after_at, row.sign_in_after_id)
        )
        for sign_in in await _sign_ins_after(session, after, room):
            content = {
                "id": str(sign_in.id),
                "occurred_at": format_time(sign_in.occurred_at),
                "actor_id": None if sign_in.user_id is None else str(sign_in.user_id),
                "outcome": sign_in.outcome,
                "reason_code": sign_in.reason,
                "method": sign_in.method,
                "client": sign_in.app,
                "action": f"sign_in.{sign_in.outcome}",
            }
            found.objects.append(siem.payload(siem.SiemStream.SIGN_INS, content))
            found.lines.append(siem.body(siem.SiemStream.SIGN_INS, content, fmt, version=VERSION))
            found.last_sign_in = (sign_in.occurred_at, sign_in.id)
    return found


def _backoff(failures: int) -> timedelta:
    wait: timedelta = BACKOFF_FIRST * int(2 ** max(failures - 1, 0))
    return min(wait, BACKOFF_MAX)


def _failure_code(exc: Exception) -> str:
    """Any failure as this destination's own code (never the far end's or Python's text)."""
    if isinstance(exc, EgressError):
        return exc.code or UNREACHABLE
    if isinstance(exc, ssl.SSLError):
        return TLS
    if isinstance(exc, FieldKeysUnavailable):
        return KEYS
    return FAILED


async def _attempt(
    session: AsyncSession,
    settings: Settings,
    row: SiemDestination,
    tenant_id: uuid.UUID,
    batch: _Batch,
) -> str | None:
    """Send a batch; the failure's code, or None.

    Nothing a destination does escapes it, so one broken destination (a bad PEM, a key it can't
    open) never stops the others (lane B (1)).
    """
    try:
        # A savepoint: a database error inside the send (opening a sealed value) rolls back to
        # here, so the failure can still be recorded on the row (lane B's #564 note).
        async with session.begin_nested():
            if row.kind == siem.SiemKind.WEBHOOK:
                await _send_webhook(session, settings, row, batch.objects, tenant_id)
            else:
                await _send_syslog(session, settings, row, batch.lines)
    except Exception as exc:  # noqa: BLE001 - every failure becomes this destination's code
        code = _failure_code(exc)
        if code == FAILED:
            log.warning("siem_send_failed", destination_id=str(row.id), error=type(exc).__name__)
        return code
    return None


async def deliver_one(
    session: AsyncSession, settings: Settings, row: SiemDestination, tenant_id: uuid.UUID
) -> bool:
    """One attempt for one destination: send the next batch, move the cursors only on success.

    Returns whether there may be more to send right away.
    """
    now = system_clock.now()
    batch = await _batch(session, row)
    if not batch.objects and batch.last_seq is None:
        return False
    if batch.objects:
        error = await _attempt(session, settings, row, tenant_id, batch)
        if error is not None:
            row.failures += 1
            row.last_error_code = error
            row.last_error_at = now
            row.failing_since = row.failing_since or now
            row.next_attempt_at = now + _backoff(row.failures)
            await session.flush()
            return False
    if batch.last_seq is not None:
        row.audit_seq_sent = batch.last_seq
    if batch.last_sign_in is not None:
        row.sign_in_after_at, row.sign_in_after_id = batch.last_sign_in
    row.failures = 0
    row.failing_since = None
    row.last_success_at = now
    row.next_attempt_at = None
    await session.flush()
    return len(batch.objects) >= siem.BATCH_MAX


async def deliver_tenant(database: Database, settings: Settings, tenant_id: uuid.UUID) -> None:
    """Every due destination of one tenant, each in its own transaction (the schedule's step)."""
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        entitled = await has_feature(tenant_id, Feature.SIEM_STREAM)
        due = list(
            await session.scalars(
                select(SiemDestination.id).where(
                    SiemDestination.deleted_at.is_(None),
                    SiemDestination.enabled.is_(True),
                    (SiemDestination.next_attempt_at.is_(None))
                    | (SiemDestination.next_attempt_at <= system_clock.now()),
                )
            )
        )
    if not entitled:
        return  # a lapsed licence pauses delivery; the cursors wait where they are
    for destination_id in due:
        for _ in range(10):  # a backlog drains a few batches a tick, never forever
            async with database.tenant_session(TenantContext(tenant_id)) as session:
                row = await session.scalar(
                    select(SiemDestination)
                    .where(SiemDestination.id == destination_id)
                    .with_for_update(skip_locked=True)
                )
                if row is None or not row.enabled or row.deleted_at is not None:
                    break
                try:
                    more = await deliver_one(session, settings, row, tenant_id)
                except Exception:  # the batch read itself: logged, the others go on
                    log.exception("siem_destination_failed", destination_id=str(destination_id))
                    more = False
            if not more:
                break


async def send_test(
    session: AsyncSession,
    subject: Actor,
    settings: Settings,
    destination_id: uuid.UUID,
) -> str | None:
    """Send one test entry now (no cursor moves); the error code, or None when it arrived."""
    row = await _live(session, destination_id)
    content = {
        "id": str(uuid.uuid4()),
        "occurred_at": format_time(system_clock.now()),
        "action": "audit.siem_test_sent",
        "category": "security",
        "module": "audit",
        "outcome": "done",
        "object_type": "siem_destination",
        "object_id": str(row.id),
    }
    error: str | None = None
    try:  # contained like delivery (lane B (6)): any failure is this destination's code
        if row.kind == siem.SiemKind.WEBHOOK:
            await _send_webhook(
                session,
                settings,
                row,
                [siem.payload(siem.SiemStream.AUDIT, content)],
                subject.tenant_id,
            )
        else:
            line = siem.body(
                siem.SiemStream.AUDIT, content, siem.SiemFormat(row.format), version=VERSION
            )
            await _send_syslog(session, settings, row, [line])
    except Exception as exc:  # noqa: BLE001 - every failure becomes a code
        error = _failure_code(exc)
    return error


async def plaintext_destinations(session: AsyncSession) -> int:
    """How many live destinations send in plaintext (D-181: the security overview's flag)."""
    return int(
        await session.scalar(
            select(func.count()).where(
                SiemDestination.deleted_at.is_(None),
                SiemDestination.transport.in_([t.value for t in siem.PLAINTEXT]),
            )
        )
        or 0
    )
