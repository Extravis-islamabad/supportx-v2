"""Exports for auditors (REQ-AUD-009; ADR-027).

An export is requested through the API and built by the consumers worker: the entries of a time
range (optionally filtered) in chain order, with their chain values and personal data, as JSON
lines or CSV, plus `manifest.json` (range, positions, previous chain value, anchors, trusted
keys, the server's own verification result, the data file's SHA-256), `manifest.sig` (signed
with the installation key), the standalone `verify_export.py` and a README. The zip goes to
object storage and can be downloaded for 7 days.

Never silent: without configured storage the request is refused (503); if storage or the build
fails, the export is marked `failed` with a problem code that the screen shows.
"""

import csv
import hashlib
import io
import json
import uuid
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.core.logging import get_logger
from app.modules.audit.domain.integrity import GENESIS_HASH, canonical, entry_content, format_time
from app.modules.audit.events import AuditExportFinished, AuditExportRequested
from app.modules.audit.infra.models import (
    AuditAnchor,
    AuditChainLink,
    AuditExport,
    AuditPersonal,
)
from app.modules.audit.infra.signing import AnchorSigner
from app.modules.audit.service.integrity import archived_through, entries_of, verify
from app.shared.clock import Clock, system_clock
from app.shared.events import record_event
from app.shared.ids import new_id
from app.shared.storage import ObjectStorage, StorageNotConfigured, StorageUnavailable

if TYPE_CHECKING:
    from app.core.tenancy import TenantContext

log = get_logger(__name__)
EXPORT_DAYS = 7
MAX_ENTRIES = 1_000_000
BATCH = 5000
FILTER_FIELDS = ("action", "category", "outcome", "actor_id", "object_type", "object_id", "client")
VERIFIER = Path(__file__).resolve().parents[1] / "tools" / "verify_export.py"
README = """SupportX audit export
=====================

Files
  manifest.json      what the export contains: range, chain positions, anchors, trusted keys
  manifest.sig       Ed25519 signature of manifest.json by the installation key (if configured)
  audit.jsonl|csv    the entries, in chain order, with their hashes and personal data
  verify_export.py   the verifier (Python 3.10+, standard library only)

Verify
  python3 verify_export.py <this zip file>

With the `cryptography` package installed the signatures are checked too. Without it, check the
manifest signature with openssl (the public key is in manifest.json under trusted_keys):
  echo <public key hex> | xxd -r -p > key.raw
  printf '302a300506032b6570032100' | xxd -r -p | cat - key.raw > key.der
  openssl pkey -pubin -inform DER -in key.der -out key.pem
  python3 -c "import json;print(json.load(open('manifest.sig'))['signature'])" | xxd -r -p > sig.bin
  openssl pkeyutl -verify -pubin -inkey key.pem -rawin -in manifest.json -sigfile sig.bin

A "complete" export (no filter) also proves no entry is missing between its first and last
position. A filtered export proves each listed entry is unchanged; ask for an unfiltered export
to prove completeness.
"""


@dataclass(frozen=True)
class ExportRequest:
    """What an auditor asked for."""

    format: str  # jsonl | csv
    range_from: datetime | None
    range_to: datetime | None
    filters: Mapping[str, str]


async def request_export(
    session: AsyncSession,
    request: ExportRequest,
    *,
    storage_ready: bool,
    clock: Clock = system_clock,
) -> AuditExport:
    """Record the request and hand it to the worker (raises 503 without storage)."""
    if not storage_ready:
        raise StorageNotConfigured
    context: TenantContext = session.info["supportx.tenant"]
    row = AuditExport(
        id=new_id(),
        tenant_id=context.tenant_id,
        status="running",
        format=request.format,
        range_from=request.range_from,
        range_to=request.range_to,
        filters=dict(request.filters),
        requested_by=context.user_id,
        created_at=clock.now(),
    )
    session.add(row)
    await session.flush()
    await record_event(session, AuditExportRequested(export_id=row.id), aggregate_id=row.id)
    return row


async def list_exports(session: AsyncSession, limit: int = 20) -> list[AuditExport]:
    """Newest first."""
    return list(
        await session.scalars(
            select(AuditExport).order_by(AuditExport.created_at.desc()).limit(limit)
        )
    )


async def download(
    session: AsyncSession, storage: ObjectStorage, export_id: uuid.UUID
) -> tuple[AuditExport, bytes]:
    """The zip of a ready export (404 unknown, 409 not ready or expired, 503 storage down)."""
    row = await session.get(AuditExport, export_id)
    if row is None:
        raise NotFound(code="audit_export_not_found")
    if row.status != "ready" or row.object_key is None:
        raise Conflict(code="audit_export_not_ready", params={"status": row.status})
    data = await storage.get(row.object_key)
    if data is None:
        raise Conflict(code="audit_export_not_ready", params={"status": "expired"})
    return row, data


# --- building -----------------------------------------------------------------------------------


def _hex(value: bytes) -> str:
    return bytes(value).hex()


async def chain_records(
    session: AsyncSession,
    links_query: Select[AuditChainLink],
    filters: Mapping[str, str],
    *,
    personal: bool = True,
) -> tuple[list[dict[str, Any]], int | None, int | None]:
    """The links `links_query` selects, in chain order, with their entries (and personal data).

    Returns (records, first position, last position); raises 409 past MAX_ENTRIES.
    """
    ordered = links_query.order_by(AuditChainLink.seq).limit(MAX_ENTRIES + 1)
    links = list(await session.scalars(ordered))
    if len(links) > MAX_ENTRIES:
        raise Conflict(code="audit_export_too_large", params={"max": MAX_ENTRIES})
    first = links[0].seq if links else None
    last = links[-1].seq if links else None
    found: list[dict[str, Any]] = []
    for start in range(0, len(links), BATCH):
        batch = links[start : start + BATCH]
        ids = [link.entry_id for link in batch]
        entries = {r["id"]: dict(r) for r in (await session.execute(entries_of(batch))).mappings()}
        people: dict[uuid.UUID, dict[str, Any]] = {}
        if personal:
            for p in await session.scalars(
                select(AuditPersonal).where(AuditPersonal.entry_id.in_(ids))
            ):
                people.setdefault(p.entry_id, {})[str(p.subject_id)] = {
                    "salt": _hex(p.salt),
                    "data": dict(p.data),
                }
        for link in batch:
            entry = entries.get(link.entry_id)
            if entry is None:  # a missing entry: exported as such, the verifier will flag it
                content: dict[str, Any] = {"id": str(link.entry_id), "missing": True}
            else:
                content = entry_content(entry)
            if any(str(content.get(k)) != v for k, v in filters.items()):
                continue
            found.append(
                {
                    "seq": link.seq,
                    "prev_hash": _hex(link.prev_hash),
                    "chain_hash": _hex(link.chain_hash),
                    "entry_hash": _hex(link.entry_hash),
                    "entry": content,
                    "personal": people.get(link.entry_id, {}),
                }
            )
    return found, first, last


async def _records(
    session: AsyncSession, row: AuditExport
) -> tuple[list[dict[str, Any]], int | None, int | None]:
    # Archived positions are no longer in the live log (retention): the export starts after them.
    query = select(AuditChainLink).where(AuditChainLink.seq > await archived_through(session))
    if row.range_from is not None:
        query = query.where(AuditChainLink.entry_occurred_at >= row.range_from)
    if row.range_to is not None:
        query = query.where(AuditChainLink.entry_occurred_at < row.range_to)
    return await chain_records(session, query, row.filters)


def _data_file(fmt: str, items: list[dict[str, Any]]) -> tuple[str, bytes]:
    if fmt == "jsonl":
        lines = (json.dumps(item, sort_keys=True, ensure_ascii=False) for item in items)
        return "audit.jsonl", ("\n".join(lines) + ("\n" if items else "")).encode()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "seq",
            "occurred_at",
            "action",
            "outcome",
            "actor_id",
            "object_type",
            "object_id",
            "prev_hash",
            "chain_hash",
            "entry_hash",
            "entry",
            "personal",
        ]
    )
    for item in items:
        entry = item["entry"]
        writer.writerow(
            [
                item["seq"],
                entry.get("occurred_at"),
                entry.get("action"),
                entry.get("outcome"),
                entry.get("actor_id"),
                entry.get("object_type"),
                entry.get("object_id"),
                item["prev_hash"],
                item["chain_hash"],
                item["entry_hash"],
                canonical(entry).decode(),
                json.dumps(item["personal"], sort_keys=True, ensure_ascii=False),
            ]
        )
    return "audit.csv", out.getvalue().encode()


@dataclass(frozen=True)
class Contents:
    """What goes into an export or archive zip."""

    kind: str  # export | archive
    id: uuid.UUID
    format: str
    range_from: datetime | None
    range_to: datetime | None
    filters: dict[str, str]
    items: list[dict[str, Any]]
    first_seq: int | None
    last_seq: int | None


async def bundle(  # noqa: PLR0913 - keyword-only collaborators
    session: AsyncSession,
    contents: Contents,
    *,
    signer: AnchorSigner | None,
    trusted_keys: Mapping[str, bytes],
    server_verification: dict[str, Any] | None,
    clock: Clock = system_clock,
) -> bytes:
    """The zip: manifest (+ signature), data file, the offline verifier and a README."""
    first, last = contents.first_seq, contents.last_seq
    context: TenantContext = session.info["supportx.tenant"]
    previous = (
        await session.scalar(
            select(AuditChainLink.chain_hash).where(AuditChainLink.seq == first - 1)
        )
        if first is not None and first > 1
        else GENESIS_HASH
    )
    anchors = list(
        await session.scalars(
            select(AuditAnchor)
            .where(AuditAnchor.seq >= (first or 1), AuditAnchor.seq <= (last or 0))
            .order_by(AuditAnchor.seq)
        )
    )
    data_name, data = _data_file(contents.format, contents.items)
    manifest = {
        "format_version": 1,
        "format": contents.format,
        "kind": contents.kind,
        "tenant_id": str(context.tenant_id),
        f"{contents.kind}_id": str(contents.id),
        "generated_at": format_time(clock.now()),
        "range_from": format_time(contents.range_from) if contents.range_from else None,
        "range_to": format_time(contents.range_to) if contents.range_to else None,
        "filters": contents.filters,
        "complete": not contents.filters,
        "first_seq": first,
        "last_seq": last,
        "previous_chain_hash": _hex(previous or GENESIS_HASH),
        "entries": len(contents.items),
        "data_file": data_name,
        "data_sha256": hashlib.sha256(data).hexdigest(),
        "anchors": [
            {
                "seq": a.seq,
                "chain_hash": _hex(a.chain_hash),
                "created_at": format_time(a.created_at),
                "key_id": a.key_id,
                "public_key": _hex(a.public_key),
                "signature": _hex(a.signature),
            }
            for a in anchors
        ],
        "trusted_keys": {key_id: _hex(key) for key_id, key in trusted_keys.items()},
        "server_verification": server_verification,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False).encode()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as out:
        out.writestr("manifest.json", manifest_bytes)
        if signer is not None:
            signature = {"key_id": signer.key_id, "signature": signer.sign(manifest_bytes).hex()}
            out.writestr("manifest.sig", json.dumps(signature))
        out.writestr(data_name, data)
        out.writestr("verify_export.py", VERIFIER.read_bytes())
        out.writestr("README.txt", README)
    return archive.getvalue()


async def build_export(  # noqa: PLR0913 - keyword-only collaborators
    session: AsyncSession,
    export_id: uuid.UUID,
    *,
    storage: ObjectStorage | None,
    signer: AnchorSigner | None,
    trusted_keys: Mapping[str, bytes],
    clock: Clock = system_clock,
) -> AuditExport | None:
    """Build, upload and mark the export ready, or mark it failed with a reason."""
    row = await session.get(AuditExport, export_id, with_for_update=True)
    if row is None or row.status != "running":
        return row
    if storage is None:
        return await _finish(session, row, "storage_not_configured", clock)
    try:
        items, first, last = await _records(session, row)
        checked = await verify(
            session,
            kind="on_demand",
            trusted_keys=trusted_keys,
            range_from=row.range_from,
            range_to=row.range_to,
            requested_by=row.requested_by,
        )
        payload = await bundle(
            session,
            Contents(
                kind="export",
                id=row.id,
                format=row.format,
                range_from=row.range_from,
                range_to=row.range_to,
                filters=dict(row.filters),
                items=items,
                first_seq=first,
                last_seq=last,
            ),
            signer=signer,
            trusted_keys=trusted_keys,
            server_verification={
                "status": checked.status,
                "entries_checked": checked.entries_checked,
                "problem": checked.finding.problem.value if checked.finding else None,
            },
            clock=clock,
        )
        key = f"audit/exports/{row.tenant_id}/{row.id}.zip"
        await storage.put(key, payload, "application/zip")
    except (StorageUnavailable, Conflict) as exc:
        log.exception("audit_export_failed", export_id=str(row.id))
        return await _finish(session, row, exc.instance_code, clock)
    else:
        row.status = "ready"
        row.object_key = key
        row.size_bytes = len(payload)
        row.sha256 = hashlib.sha256(payload).hexdigest()
        row.entries = len(items)
        row.verification = checked.status
        row.finished_at = clock.now()
        row.expires_at = clock.now() + timedelta(days=EXPORT_DAYS)
    return await _finish(session, row, None, clock)


async def _finish(
    session: AsyncSession, row: AuditExport, problem: str | None, clock: Clock
) -> AuditExport:
    """Mark the export ready (problem None) or failed, and tell open screens."""
    if problem is not None:
        row.status = "failed"
        row.problem = problem
        row.finished_at = clock.now()
    await session.flush()
    await record_event(
        session,
        AuditExportFinished(export_id=row.id, status=row.status, problem=row.problem),
        aggregate_id=row.id,
    )
    return row


async def expire_exports(
    session: AsyncSession, storage: ObjectStorage | None, clock: Clock = system_clock
) -> int:
    """Remove export files past their 7 days; returns how many were expired."""
    rows = list(
        await session.scalars(
            select(AuditExport).where(
                AuditExport.status == "ready", AuditExport.expires_at < clock.now()
            )
        )
    )
    for row in rows:
        if storage is not None and row.object_key:
            await storage.delete(row.object_key)
        row.status = "expired"
        row.object_key = None
    await session.flush()
    return len(rows)
