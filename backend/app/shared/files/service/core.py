"""Shared pieces of the files service: configuration, tenant data keys, settings, usage."""

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY
from app.core.errors import ServiceUnavailable
from app.core.tenancy import TenantContext
from app.shared.files.domain.types import DEFAULT_BLOCKED_EXTENSIONS
from app.shared.files.infra.models import FileSettings, TenantDataKey, TenantStorageUsage
from app.shared.files.infra.scanner import ClamdScanner, NoScanner, Scanner
from app.shared.files.keyring import KEY_BYTES, KeyRing
from app.shared.storage import ObjectStorage, StorageNotConfigured, storage_from

MB = 1_000_000
GB = 1_000_000_000


class FilesNotConfiguredError(ServiceUnavailable):
    """No installation key ring: files cannot be stored encrypted, so they are not stored."""

    code = "files_not_configured"


@dataclass(frozen=True)
class FileServices:
    """What the files service runs with (built from settings; tests pass fakes)."""

    storage: ObjectStorage | None
    keyring: KeyRing | None
    scanner: Scanner
    scan_required: bool = True
    link_ttl: timedelta = timedelta(minutes=5)
    signature_max_age: timedelta = timedelta(days=7)
    upload_concurrency: int = 8

    @classmethod
    def from_settings(cls, settings: Settings) -> "FileServices":
        """The installation's storage, key ring and scanner."""
        try:
            storage: ObjectStorage | None = storage_from(settings)
        except StorageNotConfigured:
            storage = None
        keys = settings.files_keys
        scanner: Scanner = (
            ClamdScanner.from_address(
                settings.files_clamd_address, settings.files_clamd_timeout_seconds
            )
            if settings.files_clamd_address
            else NoScanner()
        )
        return cls(
            storage=storage,
            keyring=KeyRing.parse(keys.get_secret_value()) if keys is not None else None,
            scanner=scanner,
            scan_required=settings.files_scan_required,
            link_ttl=timedelta(seconds=settings.files_link_ttl_seconds),
            signature_max_age=timedelta(days=settings.files_signature_max_age_days),
            upload_concurrency=settings.files_upload_concurrency,
        )

    def require_storage(self) -> tuple[ObjectStorage, KeyRing]:
        """Storage and keys, or the visible reason why files cannot be stored."""
        if self.storage is None:
            raise StorageNotConfigured
        if self.keyring is None:
            raise FilesNotConfiguredError
        return self.storage, self.keyring


def tenant_of(session: AsyncSession) -> uuid.UUID:
    """The tenant of a tenant session (TypeError outside one: files are always a tenant's)."""
    context = session.info.get(SESSION_TENANT_KEY)
    if not isinstance(context, TenantContext):
        msg = "files need a tenant session (Database.tenant_session)"
        raise TypeError(msg)
    return context.tenant_id


def now() -> datetime:
    """The current time (one place to fake it)."""
    return datetime.now(UTC)


def object_key(tenant_id: uuid.UUID, file_id: uuid.UUID, *, thumbnail: bool = False) -> str:
    """Where a file's (or its thumbnail's) ciphertext lives."""
    suffix = ".thumb" if thumbnail else ""
    return f"tenants/{tenant_id}/files/{file_id}{suffix}"


# --- data keys -----------------------------------------------------------------------------------


async def current_data_key(session: AsyncSession, keyring: KeyRing) -> tuple[uuid.UUID, bytes]:
    """The tenant's newest data key (created on first use): (id, key)."""
    tenant = tenant_of(session)
    row = await session.scalar(
        select(TenantDataKey)
        .where(TenantDataKey.retired_at.is_(None))
        .order_by(TenantDataKey.created_at.desc(), TenantDataKey.id.desc())
        .limit(1)
    )
    if row is None:
        key = os.urandom(KEY_BYTES)
        kek_id, wrapped = keyring.wrap(tenant, key)
        row = TenantDataKey(tenant_id=tenant, kek_id=kek_id, wrapped=wrapped)
        session.add(row)
        await session.flush()
        return row.id, key
    return row.id, keyring.unwrap(tenant, row.kek_id, row.wrapped)


async def data_key(session: AsyncSession, keyring: KeyRing, key_id: uuid.UUID) -> bytes:
    """A tenant data key by ID (retired keys still open their old files)."""
    tenant = tenant_of(session)
    row = await session.get(TenantDataKey, key_id)
    if row is None or row.tenant_id != tenant:
        raise FilesNotConfiguredError(params={"reason": "data_key_missing"})
    return keyring.unwrap(tenant, row.kek_id, row.wrapped)


async def rotate_data_key(session: AsyncSession, keyring: KeyRing) -> uuid.UUID:
    """Retire the tenant's current data key and start a new one (old files keep theirs)."""
    await session.execute(
        update(TenantDataKey).where(TenantDataKey.retired_at.is_(None)).values(retired_at=now())
    )
    key_id, _ = await current_data_key(session, keyring)
    return key_id


async def rewrap_data_keys(session: AsyncSession, keyring: KeyRing) -> int:
    """Re-wrap the tenant's data keys under the active installation key (after rotation)."""
    tenant = tenant_of(session)
    moved = 0
    for row in await session.scalars(
        select(TenantDataKey).where(TenantDataKey.kek_id != keyring.active_id)
    ):
        key = keyring.unwrap(tenant, row.kek_id, row.wrapped)
        row.kek_id, row.wrapped = keyring.wrap(tenant, key)
        moved += 1
    return moved


# --- settings and usage --------------------------------------------------------------------------


@dataclass(frozen=True)
class Rules:
    """A tenant's file rules in force."""

    max_file_bytes: int
    max_file_mb: int
    max_batch: int
    blocked: list[str]
    version: int


DEFAULT_RULES = Rules(
    max_file_bytes=25 * MB,
    max_file_mb=25,
    max_batch=20,
    blocked=sorted(DEFAULT_BLOCKED_EXTENSIONS),
    version=0,
)


async def rules(session: AsyncSession) -> Rules:
    """The tenant's rules (the defaults until an administrator saves some)."""
    row = await session.scalar(select(FileSettings))
    if row is None:
        return DEFAULT_RULES
    return Rules(
        max_file_bytes=row.max_file_mb * MB,
        max_file_mb=row.max_file_mb,
        max_batch=row.max_batch,
        blocked=list(row.blocked_extensions),
        version=row.version,
    )


async def lock_usage(session: AsyncSession) -> TenantStorageUsage:
    """The tenant's usage row, locked for this transaction (created on first use)."""
    tenant = tenant_of(session)
    await session.execute(
        insert(TenantStorageUsage)
        .values(tenant_id=tenant, bytes_used=0, files_count=0)
        .on_conflict_do_nothing(index_elements=["tenant_id"])
    )
    row = await session.scalar(select(TenantStorageUsage).with_for_update())
    assert row is not None  # noqa: S101 - inserted just above
    return row


async def usage(session: AsyncSession) -> tuple[int, int]:
    """(bytes stored, files stored) for the tenant."""
    row = await session.scalar(select(TenantStorageUsage))
    return (row.bytes_used, row.files_count) if row is not None else (0, 0)
