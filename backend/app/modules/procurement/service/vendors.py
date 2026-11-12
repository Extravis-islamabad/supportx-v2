"""Vendors (REQ-PUR-001; WP-049a s2, the minimal procurement module; WP-054 adds the rest).

Anyone with `vendors.view` reads them (asset and, later, contract and purchase forms pick one).
`vendors.create` adds one, also inline from another form (AC3); `vendors.manage` changes and
deletes them. An inactive vendor stays on the records that name it but cannot be picked on new
ones (AC2). A vendor that records still name cannot be deleted: the modules that point at
vendors say how many rows use one (`register_vendor_usage`). Every save keeps field history and
writes its event to the outbox in the same transaction; changes need the version read.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed
from app.modules.identity_access import Subject
from app.modules.procurement.domain.vendors import Problem, clean_vendor
from app.modules.procurement.events import VendorAction, VendorChanged
from app.modules.procurement.infra.models import Vendor
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes
from app.shared.history.conflicts import stale_version
from app.shared.ids import new_id

VIEW = "vendors.view"
CREATE = "vendors.create"
MANAGE = "vendors.manage"
RECORD_TYPE = "vendor"

VENDOR_FIELDS = ResourceFields(
    name="vendors",
    fields={
        "name": FilterField(Vendor.name, FieldType.STRING, sortable=True),
        "currency": FilterField(Vendor.currency, FieldType.STRING),
        "is_active": FilterField(Vendor.is_active, FieldType.BOOLEAN),
        "updated_at": FilterField(Vendor.updated_at, FieldType.DATETIME, sortable=True),
        "created_at": FilterField(Vendor.created_at, FieldType.DATETIME, sortable=True),
    },
    id_column=Vendor.id,
    default_sort=("name",),
)

# How many rows of another module name a vendor (assets now; contracts and orders in WP-054).
VendorUsage = Callable[[AsyncSession, uuid.UUID], Awaitable[int]]
_USAGE: list[VendorUsage] = []


def register_vendor_usage(counter: VendorUsage) -> None:
    """Called once at import by a module whose records name vendors."""
    if counter not in _USAGE:
        _USAGE.append(counter)


def _tenant(session: AsyncSession) -> uuid.UUID:
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant


def _require(subject: Subject, permission: str) -> None:
    if not subject.holds(permission):
        raise PermissionDenied(params={"permission": permission})


def _refuse(problems: list[Problem]) -> None:
    if problems:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field=f"body.{p.field}",
                    code=p.code,
                    message_key=f"errors.field.{p.code}",
                    params=dict(p.params),
                )
                for p in problems
            ]
        )


async def _name_taken(session: AsyncSession, name: str, other_than: uuid.UUID | None) -> bool:
    statement = select(Vendor.id).where(
        func.lower(Vendor.name) == name.lower(), Vendor.deleted_at.is_(None)
    )
    if other_than is not None:
        statement = statement.where(Vendor.id != other_than)
    return await session.scalar(statement.limit(1)) is not None


async def _saved(  # noqa: PLR0913 - one save: what, who, the changes, how, where from
    session: AsyncSession,
    subject: Subject,
    row: Vendor,
    changes: list[Change],
    *,
    action: VendorAction,
    source: Source,
) -> None:
    if action != "created":
        row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await session.refresh(row)  # the database's timestamps
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind=action,
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        VendorChanged(
            vendor_id=row.id, action=action, changed_fields=sorted({c.field for c in changes})
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def _locked(session: AsyncSession, vendor_id: uuid.UUID) -> Vendor:
    row = await session.scalar(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.deleted_at.is_(None)).with_for_update()
    )
    if row is None:
        raise NotFound(code="vendor_not_found")
    return row


def rows(subject: Subject) -> Select[Vendor]:
    """The live vendors the subject may list (all of the tenant's, with vendors.view)."""
    _require(subject, VIEW)
    return select(Vendor).where(Vendor.deleted_at.is_(None))


async def get_vendor(session: AsyncSession, subject: Subject, vendor_id: uuid.UUID) -> Vendor:
    """One live vendor."""
    _require(subject, VIEW)
    row = await session.scalar(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.deleted_at.is_(None))
    )
    if row is None:
        raise NotFound(code="vendor_not_found")
    return row


async def create_vendor(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], *, source: Source
) -> Vendor:
    """A new, active vendor (vendors.create, also inline from another form: AC3)."""
    _require(subject, CREATE)
    cleaned, problems = clean_vendor(values)
    if "name" not in cleaned and not any(p.field == "name" for p in problems):
        problems.append(Problem("name", "required"))
    if "name" in cleaned and await _name_taken(session, cleaned["name"], None):
        problems.append(Problem("name", "vendor_name_taken"))
    _refuse(problems)
    row = Vendor(
        id=new_id(),
        tenant_id=_tenant(session),
        created_by=subject.user_id,
        **{"is_active": True, **cleaned},
    )
    session.add(row)
    await session.flush()
    changes = [Change(k, None, v) for k, v in cleaned.items() if v is not None]
    await _saved(session, subject, row, changes, action="created", source=source)
    return row


async def update_vendor(  # noqa: PLR0913 - the If-Match and the source
    session: AsyncSession,
    subject: Subject,
    vendor_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> Vendor:
    """Change the fields sent (vendors.manage). Making a vendor inactive keeps it on records."""
    _require(subject, MANAGE)
    row = await _locked(session, vendor_id)
    if row.version != expected_version:
        raise await stale_version(
            session,
            row,
            expected_version=expected_version,
            record_type=RECORD_TYPE,
            record_id=row.id,
        )
    cleaned, problems = clean_vendor(values)
    if "name" in cleaned and await _name_taken(session, cleaned["name"], row.id):
        problems.append(Problem("name", "vendor_name_taken"))
    _refuse(problems)
    changes: list[Change] = []
    for field, value in cleaned.items():
        if getattr(row, field) != value:
            changes.append(Change(field, getattr(row, field), value))
            setattr(row, field, value)
    if changes:
        await _saved(session, subject, row, changes, action="updated", source=source)
    return row


async def delete_vendor(
    session: AsyncSession,
    subject: Subject,
    vendor_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """To the trash (vendors.manage); refused while records name it (409 `vendor_in_use`)."""
    _require(subject, MANAGE)
    row = await _locked(session, vendor_id)
    if row.version != expected_version:
        raise await stale_version(
            session,
            row,
            expected_version=expected_version,
            record_type=RECORD_TYPE,
            record_id=row.id,
        )
    used = sum([await count(session, row.id) for count in _USAGE])
    if used:
        raise Conflict(code="vendor_in_use", params={"used": used})
    row.deleted_at = datetime.now(UTC)
    deleted = Change("deleted", old=False, new=True)
    await _saved(session, subject, row, [deleted], action="deleted", source=source)


# --- the public interface for other modules ---------------------------------------------------


async def vendor_problem(
    session: AsyncSession, vendor_id: uuid.UUID, *, current: uuid.UUID | None = None
) -> str | None:
    """Why `vendor_id` cannot be set on a record (a code), or None.

    `current` is the record's vendor now, which may stay even when inactive (AC2). Codes:
    vendor_not_found, vendor_inactive.
    """
    active = await session.scalar(
        select(Vendor.is_active).where(Vendor.id == vendor_id, Vendor.deleted_at.is_(None))
    )
    if active is None:
        return "vendor_not_found"
    if not active and vendor_id != current:
        return "vendor_inactive"
    return None


async def find_vendor(session: AsyncSession, name: str) -> Vendor | None:
    """The live vendor of this name, case and spacing aside (imports match rows by it)."""
    wanted = " ".join(name.split()).lower()
    if not wanted:
        return None
    found: Vendor | None = await session.scalar(
        select(Vendor).where(func.lower(Vendor.name) == wanted, Vendor.deleted_at.is_(None))
    )
    return found


async def find_vendor_id(session: AsyncSession, name: str) -> uuid.UUID | None:
    """The ID of the live vendor of this name (an asset import's vendor column)."""
    found = await find_vendor(session, name)
    return None if found is None else found.id


async def vendor_names(session: AsyncSession, vendor_ids: Sequence[uuid.UUID]) -> dict[str, str]:
    """{vendor id: name} for display (deleted vendors too: old records still name them)."""
    if not vendor_ids:
        return {}
    found = await session.execute(
        select(Vendor.id, Vendor.name).where(Vendor.id.in_(set(vendor_ids)))
    )
    return {str(row.id): row.name for row in found}


async def vendor_report_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """Vendor names for report files (the reporting port's resolver; one name per vendor)."""
    del language, field
    ids: list[uuid.UUID] = []
    for value in values:
        try:
            ids.append(uuid.UUID(value))
        except ValueError:
            continue
    return await vendor_names(session, ids)
