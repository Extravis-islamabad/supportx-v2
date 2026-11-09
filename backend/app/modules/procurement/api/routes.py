"""Procurement HTTP API under /api/v1/procurement (WP-049a s2: vendors). No business logic.

Reading vendors needs `vendors.view`; adding one `vendors.create`; changing or deleting one
`vendors.manage`. Writes use If-Match; creates take an Idempotency-Key.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import audited
from app.modules.identity_access import Subject
from app.modules.procurement.domain import vendors as rules
from app.modules.procurement.infra.models import Vendor
from app.modules.procurement.service import vendors as service
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, Page, list_query, paginate
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

Responses = dict[int | str, dict[str, object]]
WRITE: Responses = {
    404: {"model": ProblemDetail, "description": "vendor_not_found"},
    409: {"model": ProblemDetail, "description": "version_conflict, or vendor_in_use."},
}

router = APIRouter(
    prefix="/procurement",
    tags=["procurement"],
    dependencies=[Depends(rate_limit("procurement"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    },
)

View = Annotated[Subject, Depends(require_permission(service.VIEW))]
Create = Annotated[Subject, Depends(require_permission(service.CREATE))]
Manage = Annotated[Subject, Depends(require_permission(service.MANAGE))]
VendorsQuery = Annotated[ListQuery, Depends(list_query(service.VENDOR_FIELDS))]


class VendorOut(BaseModel):
    """A vendor (REQ-PUR-001)."""

    id: uuid.UUID
    name: str
    currency: str | None
    description: str | None
    contact_person: str | None
    address: str | None
    email: str | None
    phone: str | None
    fax: str | None
    website: str | None
    is_active: bool = Field(description="Inactive: stays on old records, not offered on new.")
    updated_at: datetime
    version: int

    @classmethod
    def of(cls, row: Vendor) -> "VendorOut":
        """From the row."""
        return cls(
            id=row.id,
            name=row.name,
            currency=row.currency,
            description=row.description,
            contact_person=row.contact_person,
            address=row.address,
            email=row.email,
            phone=row.phone,
            fax=row.fax,
            website=row.website,
            is_active=row.is_active,
            updated_at=row.updated_at,
            version=row.version,
        )


class VendorIn(BaseModel):
    """A new vendor."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=rules.NAME_MAX)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    description: str | None = Field(default=None, max_length=rules.TEXT_MAX)
    contact_person: str | None = Field(default=None, max_length=rules.SHORT_MAX)
    address: str | None = Field(default=None, max_length=rules.TEXT_MAX)
    email: str | None = Field(default=None, max_length=rules.EMAIL_MAX)
    phone: str | None = Field(default=None, max_length=rules.SHORT_MAX)
    fax: str | None = Field(default=None, max_length=rules.SHORT_MAX)
    website: str | None = Field(default=None, max_length=rules.URL_MAX)


class VendorPatch(BaseModel):
    """Vendor fields to change (only those sent; null clears an optional one)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=rules.NAME_MAX)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    description: str | None = Field(default=None, max_length=rules.TEXT_MAX)
    contact_person: str | None = Field(default=None, max_length=rules.SHORT_MAX)
    address: str | None = Field(default=None, max_length=rules.TEXT_MAX)
    email: str | None = Field(default=None, max_length=rules.EMAIL_MAX)
    phone: str | None = Field(default=None, max_length=rules.SHORT_MAX)
    fax: str | None = Field(default=None, max_length=rules.SHORT_MAX)
    website: str | None = Field(default=None, max_length=rules.URL_MAX)
    is_active: bool | None = None


_REQUIRED = {"name", "is_active"}


@router.get("/vendors", summary="Vendors")
async def list_vendors(
    session: TenantSession, query: VendorsQuery, subject: View
) -> Page[VendorOut]:
    """Vendors, filtered (`is_active=`, the DSL) and paged, by name unless sorted otherwise."""
    page = await paginate(session, service.rows(subject), query)
    return Page[VendorOut](
        items=[VendorOut.of(row) for row in page.rows],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        estimated_total=page.estimated_total,
    )


@router.post(
    "/vendors",
    summary="Add a vendor",
    status_code=status.HTTP_201_CREATED,
    response_model=VendorOut,
    dependencies=[audited("vendor.created", object_type="vendor")],
)
async def create_vendor(
    body: VendorIn,
    session: TenantSession,
    subject: Create,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """A new, active vendor (also inline from another form). Send an Idempotency-Key."""

    async def run() -> Created:
        row = await service.create_vendor(
            session, subject, body.model_dump(exclude_none=True), source=source_of(request)
        )
        return Created(body=VendorOut.of(row), headers={"ETag": f'"{row.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get(
    "/vendors/{vendor_id}",
    summary="Get a vendor",
    responses={404: {"model": ProblemDetail, "description": "vendor_not_found"}},
)
async def get_vendor(
    vendor_id: uuid.UUID, session: TenantSession, subject: View, response: Response
) -> VendorOut:
    """One vendor."""
    row = await service.get_vendor(session, subject, vendor_id)
    set_etag(response, row.version)
    return VendorOut.of(row)


@router.patch(
    "/vendors/{vendor_id}",
    summary="Change a vendor",
    responses=WRITE,
    dependencies=[audited("vendor.updated", object_type="vendor", object_param="vendor_id")],
)
async def patch_vendor(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    vendor_id: uuid.UUID,
    body: VendorPatch,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> VendorOut:
    """Change the fields sent (If-Match)."""
    sent = body.model_dump(include=body.model_fields_set)
    values = {k: v for k, v in sent.items() if v is not None or k not in _REQUIRED}
    row = await service.update_vendor(
        session, subject, vendor_id, values, expected_version=version, source=source_of(request)
    )
    set_etag(response, row.version)
    return VendorOut.of(row)


@router.delete(
    "/vendors/{vendor_id}",
    summary="Delete a vendor",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
    dependencies=[audited("vendor.deleted", object_type="vendor", object_param="vendor_id")],
)
async def delete_vendor(
    vendor_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    request: Request,
) -> None:
    """Moves it to the trash; refused while records name it (409 vendor_in_use)."""
    await service.delete_vendor(
        session, subject, vendor_id, expected_version=version, source=source_of(request)
    )
