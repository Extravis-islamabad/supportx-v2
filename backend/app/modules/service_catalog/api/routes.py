"""The service catalog over HTTP (WP-030 s1, plan D2). Admin screens come with WP-031.

GET   /api/v1/catalog/categories            every category (names only)
POST  /api/v1/catalog/categories            add one (catalog_items.manage), Idempotency-Key
GET   /api/v1/catalog/items                 what the viewer may raise
GET   /api/v1/catalog/items/{id}            one item
POST  /api/v1/catalog/items                 add one (catalog_items.manage), Idempotency-Key
PATCH /api/v1/catalog/items/{id}            change it (If-Match)
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import Subject
from app.modules.service_catalog.domain.items import ApproverKind, ItemAudience, QuestionKind
from app.modules.service_catalog.infra.models import ServiceCategory
from app.modules.service_catalog.service import catalog as service
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

SignedIn = Annotated[Subject, Depends(require_signed_in())]

router = APIRouter(
    prefix="/catalog", tags=["catalog"], dependencies=[Depends(rate_limit("catalog"))]
)


class QuestionIO(BaseModel):
    """A form question."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(max_length=40)
    label: dict[str, str]
    kind: QuestionKind
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=50)


class ApproverIO(BaseModel):
    """An approver: a named person, or the requested-for person's manager."""

    model_config = ConfigDict(extra="forbid")

    kind: ApproverKind
    person_id: uuid.UUID | None = None


class ApprovalIO(BaseModel):
    """The item's approval stage (one at MVP)."""

    model_config = ConfigDict(extra="forbid")

    approvers: list[ApproverIO] = Field(max_length=10)
    backup_id: uuid.UUID | None = None
    comments_required: bool = False
    self_approval: bool = False


class PlannedTaskIO(BaseModel):
    """A fulfilment task the plan creates."""

    model_config = ConfigDict(extra="forbid")

    title: dict[str, str]
    group_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    required: bool = True
    internal: bool = False


class CatalogItemIn(BaseModel):
    """What an item decides for its requests (only what is sent changes, on PATCH)."""

    model_config = ConfigDict(extra="forbid")

    names: dict[str, str] | None = None
    descriptions: dict[str, str] | None = None
    category_id: uuid.UUID | None = None
    audience: ItemAudience | None = None
    enabled: bool | None = None
    questions: list[QuestionIO] | None = Field(default=None, max_length=30)
    approval: ApprovalIO | None = None
    plan: list[PlannedTaskIO] | None = Field(default=None, max_length=20)
    default_priority: str | None = Field(default=None, max_length=10)
    requester_sets_priority: bool | None = None
    sla_policy_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    technician_id: uuid.UUID | None = None
    technician_after_approval: bool | None = None
    count_approval_time: bool | None = None
    auto_fulfil: bool | None = None


class CatalogItemOut(BaseModel):
    """An item as screens show it; staff see the whole item, others what they raise it with."""

    id: uuid.UUID
    names: dict[str, str]
    descriptions: dict[str, str]
    category_id: uuid.UUID | None
    audience: ItemAudience
    enabled: bool
    questions: list[QuestionIO]
    approval: ApprovalIO | None
    plan: list[PlannedTaskIO]
    default_priority: str | None
    requester_sets_priority: bool
    sla_policy_id: uuid.UUID | None
    group_id: uuid.UUID | None
    technician_id: uuid.UUID | None
    technician_after_approval: bool
    count_approval_time: bool
    auto_fulfil: bool
    can_manage: bool
    version: int

    @classmethod
    def of(cls, view: service.ItemView) -> "CatalogItemOut":
        """From the service's view."""
        item = view.item
        return cls.model_validate(
            {
                **{name: getattr(item, name) for name in service.ITEM_FIELDS},
                "id": item.id,
                "can_manage": view.can_manage,
                "version": item.version,
            }
        )


class CategoryIn(BaseModel):
    """A new category."""

    model_config = ConfigDict(extra="forbid")

    names: dict[str, str]
    sort_order: int = Field(default=0, ge=0, le=10_000)


class CategoryOut(BaseModel):
    """A category."""

    id: uuid.UUID
    names: dict[str, str]
    sort_order: int
    version: int

    @classmethod
    def of(cls, row: ServiceCategory) -> "CategoryOut":
        """From the row."""
        return cls(id=row.id, names=row.names, sort_order=row.sort_order, version=row.version)


def _body(body: CatalogItemIn) -> dict[str, Any]:
    return body.model_dump(mode="json", include=body.model_fields_set)


@router.get("/categories", summary="Catalog categories")
async def list_categories(session: TenantSession, subject: SignedIn) -> list[CategoryOut]:
    """Every category, in their order."""
    del subject
    return [CategoryOut.of(c) for c in await service.list_categories(session)]


@router.post(
    "/categories",
    summary="Add a catalog category",
    status_code=status.HTTP_201_CREATED,
    response_model=CategoryOut,
    dependencies=[audited("catalog.category_changed", object_type="service_category")],
)
async def create_category(
    body: CategoryIn,
    session: TenantSession,
    subject: SignedIn,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """A new category. Send an Idempotency-Key."""

    async def run() -> Created:
        row = await service.create_category(
            session, subject, body.names, sort_order=body.sort_order, source=source_of(request)
        )
        return Created(body=CategoryOut.of(row), headers={"ETag": f'"{row.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get("/items", summary="Catalog items you may raise")
async def list_items(
    session: TenantSession,
    subject: SignedIn,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[CatalogItemOut]:
    """Staff see every item (disabled ones marked); others the enabled items open to everyone."""
    return [
        CatalogItemOut.of(v)
        for v in await service.list_items(session, subject, category_id=category_id)
    ]


@router.get("/items/{item_id}", summary="One catalog item")
async def get_item(
    item_id: uuid.UUID, session: TenantSession, subject: SignedIn, response: Response
) -> CatalogItemOut:
    """One item you may see (404 otherwise)."""
    view = await service.get_item(session, subject, item_id)
    set_etag(response, view.item.version)
    return CatalogItemOut.of(view)


@router.post(
    "/items",
    summary="Add a catalog item",
    status_code=status.HTTP_201_CREATED,
    response_model=CatalogItemOut,
)
async def create_item(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: CatalogItemIn,
    session: TenantSession,
    subject: SignedIn,
    idempotency: Idempotency,
    request: Request,
    note: Annotated[AuditNote, audited("catalog.item_changed", object_type="catalog_item")],
) -> Response:
    """A new item (an English name at least). Send an Idempotency-Key."""

    async def run() -> Created:
        view = await service.create_item(session, subject, _body(body), source=source_of(request))
        note.object_id = str(view.item.id)
        out = CatalogItemOut.of(view)
        return Created(
            body=out,
            headers={"Location": f"/api/v1/catalog/items/{out.id}", "ETag": f'"{out.version}"'},
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch("/items/{item_id}", summary="Change a catalog item")
async def update_item(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    item_id: uuid.UUID,
    body: CatalogItemIn,
    version: ExpectedVersion,
    session: TenantSession,
    subject: SignedIn,
    request: Request,
    response: Response,
    note: Annotated[
        AuditNote,
        audited("catalog.item_changed", object_type="catalog_item", object_param="item_id"),
    ],
) -> CatalogItemOut:
    """Change what is sent; If-Match with the version read (409 with what changed if stale)."""
    view = await service.update_item(
        session,
        subject,
        item_id,
        expected_version=version,
        values=_body(body),
        source=source_of(request),
    )
    note.details = {"changed_fields": sorted(body.model_fields_set)}
    set_etag(response, view.item.version)
    return CatalogItemOut.of(view)


__all__ = ["router"]
