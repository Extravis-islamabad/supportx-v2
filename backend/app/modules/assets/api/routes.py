"""Assets HTTP API under /api/v1/assets (WP-049a session 1: the catalogue). No business logic.

Reading the catalogue needs `assets.view` (the asset form uses it); changing it needs
`config.assets` or `settings.manage`. Writes use If-Match; creates take an Idempotency-Key.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission, require_signed_in
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.assets.api.records import AssetHoldingOut, AssetOut, HeldAssetOut
from app.modules.assets.domain.catalogue import (
    AssetAgeBasis,
    AssetDepreciationMethod,
    AssetStateCategory,
    AssetTypeCategory,
    AssetTypeKind,
)
from app.modules.assets.infra.models import (
    AssetAcknowledgement,
    AssetLifeCycleTransition,
    AssetProduct,
    AssetProductType,
    AssetSettings,
    AssetState,
)
from app.modules.assets.service import acknowledgements, ownership
from app.modules.assets.service import catalogue as service
from app.modules.audit import audited
from app.modules.identity_access import Subject
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, Page, list_query, paginate
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

Responses = dict[int | str, dict[str, object]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
}
WRITE: Responses = {
    404: {"model": ProblemDetail, "description": "No such item."},
    409: {"model": ProblemDetail, "description": "version_conflict, or the item is in use."},
}

router = APIRouter(
    prefix="/assets",
    tags=["assets"],
    dependencies=[Depends(rate_limit("assets"))],
    responses=RESPONSES,
)

View = Annotated[Subject, Depends(require_permission(service.VIEW, *service.CONFIGURE_ANY))]
Configure = Annotated[Subject, Depends(require_permission(*service.CONFIGURE_ANY))]
ProductsQuery = Annotated[ListQuery, Depends(list_query(service.PRODUCT_FIELDS))]
Names = dict[str, str]
NAMES_DOC = 'Names by language: {"en": ..., "ar": ..., "ur": ...}; English required.'


# --- settings ---------------------------------------------------------------------------------


class AssetSettingsOut(BaseModel):
    """The tenant's asset settings (Appendix A defaults until an admin changes them)."""

    tag_pattern: str
    age_basis: AssetAgeBasis
    cost_includes_tax: bool = Field(description="D-141: an asset's cost includes its tax.")
    copy_limit: int
    site_follows_owner: bool
    portal_own_assets_only: bool
    email_include_assets: bool
    scan_retention_months: int
    version: int

    @classmethod
    def of(cls, row: AssetSettings) -> "AssetSettingsOut":
        """From the row."""
        return cls(
            tag_pattern=row.tag_pattern,
            age_basis=AssetAgeBasis(row.age_basis),
            cost_includes_tax=row.cost_includes_tax,
            copy_limit=row.copy_limit,
            site_follows_owner=row.site_follows_owner,
            portal_own_assets_only=row.portal_own_assets_only,
            email_include_assets=row.email_include_assets,
            scan_retention_months=row.scan_retention_months,
            version=row.version,
        )


class AssetSettingsIn(BaseModel):
    """Settings to change (only those sent)."""

    model_config = ConfigDict(extra="forbid")

    tag_pattern: str | None = Field(default=None, max_length=40, description="e.g. AST-{n}")
    age_basis: AssetAgeBasis | None = None
    cost_includes_tax: bool | None = None
    copy_limit: int | None = Field(default=None, ge=1, le=500)
    site_follows_owner: bool | None = None
    portal_own_assets_only: bool | None = None
    email_include_assets: bool | None = None
    scan_retention_months: int | None = Field(default=None, ge=1, le=60)


@router.get("/settings", summary="Asset settings")
async def get_settings(
    session: TenantSession, subject: View, response: Response
) -> AssetSettingsOut:
    """The tenant's asset settings."""
    del subject
    row = await service.get_settings(session)
    set_etag(response, row.version)
    return AssetSettingsOut.of(row)


@router.patch(
    "/settings",
    summary="Change asset settings",
    responses=WRITE,
    dependencies=[audited("asset.settings_changed", object_type="asset_settings")],
)
async def patch_settings(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: AssetSettingsIn,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AssetSettingsOut:
    """Change the settings sent. If-Match: the version you read."""
    row = await service.update_settings(
        session,
        subject,
        body.model_dump(include=body.model_fields_set, exclude_none=True),
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, row.version)
    return AssetSettingsOut.of(row)


# --- states -----------------------------------------------------------------------------------


class AssetStateOut(BaseModel):
    """An asset state; `category` is its fixed meaning (REQ-AST-012)."""

    id: uuid.UUID
    code: str
    names: Names
    category: AssetStateCategory
    reason_required: bool
    is_default_for_category: bool
    system: bool = Field(description="Used by loans or disposal: it can be renamed, not deleted.")
    sort: int
    version: int

    @classmethod
    def of(cls, row: AssetState) -> "AssetStateOut":
        """From the row."""
        return cls(
            id=row.id,
            code=row.code,
            names=row.names,
            category=AssetStateCategory(row.category),
            reason_required=row.reason_required,
            is_default_for_category=row.is_default_for_category,
            system=row.system,
            sort=row.sort,
            version=row.version,
        )


class AssetStateIn(BaseModel):
    """A new state."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(max_length=40, description="Stable lowercase code, e.g. with_courier.")
    names: Names = Field(description=NAMES_DOC)
    category: AssetStateCategory
    reason_required: bool = False
    is_default_for_category: bool = False


class AssetStatePatch(BaseModel):
    """State fields to change (only those sent)."""

    model_config = ConfigDict(extra="forbid")

    names: Names | None = Field(default=None, description=NAMES_DOC)
    category: AssetStateCategory | None = None
    reason_required: bool | None = None
    is_default_for_category: bool | None = None
    sort: int | None = Field(default=None, ge=0, le=10_000)


@router.get("/states", summary="Asset states")
async def list_states(session: TenantSession, subject: View) -> list[AssetStateOut]:
    """Every state, in order."""
    del subject
    return [AssetStateOut.of(s) for s in await service.list_states(session)]


@router.post(
    "/states",
    summary="Add an asset state",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetStateOut,
    dependencies=[audited("asset.state_saved", object_type="asset_state")],
)
async def create_state(
    body: AssetStateIn,
    session: TenantSession,
    subject: Configure,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """A new state. Send an Idempotency-Key."""

    async def run() -> Created:
        row = await service.create_state(
            session, subject, body.model_dump(), source=source_of(request)
        )
        return Created(body=AssetStateOut.of(row), headers={"ETag": f'"{row.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/states/{state_id}",
    summary="Change an asset state",
    responses=WRITE,
    dependencies=[audited("asset.state_saved", object_type="asset_state", object_param="state_id")],
)
async def patch_state(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    state_id: uuid.UUID,
    body: AssetStatePatch,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AssetStateOut:
    """Change the fields sent (If-Match)."""
    row = await service.update_state(
        session,
        subject,
        state_id,
        body.model_dump(include=body.model_fields_set, exclude_none=True),
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, row.version)
    return AssetStateOut.of(row)


@router.delete(
    "/states/{state_id}",
    summary="Delete an asset state",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
    dependencies=[
        audited("asset.state_deleted", object_type="asset_state", object_param="state_id")
    ],
)
async def delete_state(
    state_id: uuid.UUID,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
    request: Request,
) -> None:
    """Refused for system states, a category's default, and states a life cycle uses."""
    await service.delete_state(
        session, subject, state_id, expected_version=version, source=source_of(request)
    )


# --- life cycles ------------------------------------------------------------------------------


class AssetMoveIO(BaseModel):
    """One allowed move between two states."""

    model_config = ConfigDict(extra="forbid")

    from_state_id: uuid.UUID
    to_state_id: uuid.UUID
    reason_required: bool = False
    permission: str | None = Field(
        default=None, max_length=80, description="A permission the move needs, if any."
    )

    @classmethod
    def of(cls, row: AssetLifeCycleTransition) -> "AssetMoveIO":
        """From the row."""
        return cls(
            from_state_id=row.from_state_id,
            to_state_id=row.to_state_id,
            reason_required=row.reason_required,
            permission=row.permission,
        )


class AssetLifeCycleOut(BaseModel):
    """A life cycle and its moves (REQ-AST-013)."""

    id: uuid.UUID
    code: str = Field(description="Stable code for integrations; never shown to end users.")
    names: Names
    is_default: bool
    moves: list[AssetMoveIO]
    version: int

    @classmethod
    def of(cls, view: service.LifeCycleView) -> "AssetLifeCycleOut":
        """From the service's view."""
        return cls(
            id=view.record.id,
            code=view.record.code,
            names=view.record.names,
            is_default=view.record.is_default,
            moves=[AssetMoveIO.of(m) for m in view.moves],
            version=view.record.version,
        )


class AssetLifeCycleIn(BaseModel):
    """A new life cycle."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(max_length=40, description="Stable lowercase code, e.g. leased_laptops.")
    names: Names = Field(description=NAMES_DOC)
    moves: list[AssetMoveIO] = Field(default_factory=list, max_length=500)


class AssetLifeCyclePatch(BaseModel):
    """Life cycle fields to change; `moves` replaces every move."""

    model_config = ConfigDict(extra="forbid")

    names: Names | None = Field(default=None, description=NAMES_DOC)
    moves: list[AssetMoveIO] | None = Field(default=None, max_length=500)
    is_default: bool | None = None


@router.get("/life-cycles", summary="Asset life cycles")
async def list_life_cycles(session: TenantSession, subject: View) -> list[AssetLifeCycleOut]:
    """Every life cycle with its moves, the default first."""
    del subject
    return [AssetLifeCycleOut.of(v) for v in await service.list_life_cycles(session)]


@router.post(
    "/life-cycles",
    summary="Add an asset life cycle",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetLifeCycleOut,
    dependencies=[audited("asset.life_cycle_saved", object_type="asset_life_cycle")],
)
async def create_life_cycle(
    body: AssetLifeCycleIn,
    session: TenantSession,
    subject: Configure,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """A new life cycle with its moves. Send an Idempotency-Key."""

    async def run() -> Created:
        view = await service.create_life_cycle(
            session, subject, body.model_dump(), source=source_of(request)
        )
        return Created(
            body=AssetLifeCycleOut.of(view), headers={"ETag": f'"{view.record.version}"'}
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/life-cycles/{life_cycle_id}",
    summary="Change an asset life cycle",
    responses=WRITE,
    dependencies=[
        audited(
            "asset.life_cycle_saved", object_type="asset_life_cycle", object_param="life_cycle_id"
        )
    ],
)
async def patch_life_cycle(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    life_cycle_id: uuid.UUID,
    body: AssetLifeCyclePatch,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AssetLifeCycleOut:
    """Change the fields sent (If-Match)."""
    view = await service.update_life_cycle(
        session,
        subject,
        life_cycle_id,
        body.model_dump(include=body.model_fields_set, exclude_none=True),
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, view.record.version)
    return AssetLifeCycleOut.of(view)


@router.delete(
    "/life-cycles/{life_cycle_id}",
    summary="Delete an asset life cycle",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
    dependencies=[
        audited(
            "asset.life_cycle_deleted", object_type="asset_life_cycle", object_param="life_cycle_id"
        )
    ],
)
async def delete_life_cycle(
    life_cycle_id: uuid.UUID,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
    request: Request,
) -> None:
    """Refused for the default and for one a product type uses."""
    await service.delete_life_cycle(
        session, subject, life_cycle_id, expected_version=version, source=source_of(request)
    )


# --- product types ----------------------------------------------------------------------------


class AssetProductTypeOut(BaseModel):
    """A node of the product type tree (REQ-AST-003)."""

    id: uuid.UUID
    parent_id: uuid.UUID | None
    api_name: str = Field(description="For integrations; never shown to end users.")
    names: Names
    icon: str | None
    category: AssetTypeCategory = Field(description="D-141: only IT assets count toward the limit.")
    kind: AssetTypeKind
    description: str | None
    life_cycle_id: uuid.UUID | None = Field(description="None: the default life cycle.")
    tag_pattern: str | None = Field(description="None: the tenant's pattern.")
    ack_required: bool
    sort: int
    version: int

    @classmethod
    def of(cls, row: AssetProductType) -> "AssetProductTypeOut":
        """From the row."""
        return cls(
            id=row.id,
            parent_id=row.parent_id,
            api_name=row.api_name,
            names=row.names,
            icon=row.icon,
            category=AssetTypeCategory(row.category),
            kind=AssetTypeKind(row.kind),
            description=row.description,
            life_cycle_id=row.life_cycle_id,
            tag_pattern=row.tag_pattern,
            ack_required=row.ack_required,
            sort=row.sort,
            version=row.version,
        )


class AssetProductTypeIn(BaseModel):
    """A new type; under a parent it takes the parent's category and kind."""

    model_config = ConfigDict(extra="forbid")

    api_name: str = Field(max_length=64)
    names: Names = Field(description=NAMES_DOC)
    parent_id: uuid.UUID | None = None
    icon: str | None = Field(default=None, max_length=40)
    category: AssetTypeCategory | None = Field(default=None, description="Top-level types only.")
    kind: AssetTypeKind | None = Field(default=None, description="Top-level types only.")
    description: str | None = Field(default=None, max_length=service.TEXT_MAX)
    life_cycle_id: uuid.UUID | None = None
    tag_pattern: str | None = Field(default=None, max_length=40)
    ack_required: bool = False


class AssetProductTypePatch(BaseModel):
    """Type fields to change (only those sent; null clears an optional one)."""

    model_config = ConfigDict(extra="forbid")

    names: Names | None = Field(default=None, description=NAMES_DOC)
    parent_id: uuid.UUID | None = None
    icon: str | None = Field(default=None, max_length=40)
    category: AssetTypeCategory | None = None
    kind: AssetTypeKind | None = None
    description: str | None = Field(default=None, max_length=service.TEXT_MAX)
    life_cycle_id: uuid.UUID | None = None
    tag_pattern: str | None = Field(default=None, max_length=40)
    ack_required: bool | None = None
    sort: int | None = Field(default=None, ge=0, le=10_000)


@router.get("/product-types", summary="Product types")
async def list_product_types(session: TenantSession, subject: View) -> list[AssetProductTypeOut]:
    """The whole tree, flat: each type names its parent."""
    del subject
    return [AssetProductTypeOut.of(t) for t in await service.list_product_types(session)]


@router.post(
    "/product-types",
    summary="Add a product type",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetProductTypeOut,
    dependencies=[audited("asset.product_type_saved", object_type="asset_product_type")],
)
async def create_product_type(
    body: AssetProductTypeIn,
    session: TenantSession,
    subject: Configure,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """A new product type. Send an Idempotency-Key."""

    async def run() -> Created:
        row = await service.create_product_type(
            session, subject, body.model_dump(exclude_none=True), source=source_of(request)
        )
        return Created(body=AssetProductTypeOut.of(row), headers={"ETag": f'"{row.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


_NULLABLE_TYPE_FIELDS = {"parent_id", "icon", "description", "life_cycle_id", "tag_pattern"}


@router.patch(
    "/product-types/{product_type_id}",
    summary="Change a product type",
    responses=WRITE,
    dependencies=[
        audited(
            "asset.product_type_saved",
            object_type="asset_product_type",
            object_param="product_type_id",
        )
    ],
)
async def patch_product_type(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    product_type_id: uuid.UUID,
    body: AssetProductTypePatch,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AssetProductTypeOut:
    """Change the fields sent (If-Match). Category and kind flow down to the types below."""
    sent = body.model_dump(include=body.model_fields_set)
    values = {k: v for k, v in sent.items() if v is not None or k in _NULLABLE_TYPE_FIELDS}
    row = await service.update_product_type(
        session,
        subject,
        product_type_id,
        values,
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, row.version)
    return AssetProductTypeOut.of(row)


@router.delete(
    "/product-types/{product_type_id}",
    summary="Delete a product type",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
    dependencies=[
        audited(
            "asset.product_type_deleted",
            object_type="asset_product_type",
            object_param="product_type_id",
        )
    ],
)
async def delete_product_type(
    product_type_id: uuid.UUID,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
    request: Request,
) -> None:
    """Refused while types sit below it or products use it (the count is in the problem)."""
    await service.delete_product_type(
        session, subject, product_type_id, expected_version=version, source=source_of(request)
    )


# --- products ---------------------------------------------------------------------------------


class AssetProductOut(BaseModel):
    """A product (REQ-AST-005); D-141: price and tax apart, `total` is their sum."""

    id: uuid.UUID
    product_type_id: uuid.UUID
    name: str
    manufacturer: str | None
    part_number: str | None
    price: Decimal | None
    tax: Decimal | None
    total: Decimal | None
    currency: str | None
    gl_code: str | None
    hide_from_purchase_orders: bool
    depreciation_method: AssetDepreciationMethod | None
    useful_life_years: int | None
    salvage_value: Decimal | None
    description: str | None
    updated_at: datetime
    version: int

    @classmethod
    def of(cls, row: AssetProduct) -> "AssetProductOut":
        """From the row."""
        return cls(
            id=row.id,
            product_type_id=row.product_type_id,
            name=row.name,
            manufacturer=row.manufacturer,
            part_number=row.part_number,
            price=row.price,
            tax=row.tax,
            total=service.product_total(row),
            currency=row.currency,
            gl_code=row.gl_code,
            hide_from_purchase_orders=row.hide_from_purchase_orders,
            depreciation_method=(
                AssetDepreciationMethod(row.depreciation_method)
                if row.depreciation_method
                else None
            ),
            useful_life_years=row.useful_life_years,
            salvage_value=row.salvage_value,
            description=row.description,
            updated_at=row.updated_at,
            version=row.version,
        )


class AssetProductIn(BaseModel):
    """A new product."""

    model_config = ConfigDict(extra="forbid")

    product_type_id: uuid.UUID
    name: str = Field(min_length=1, max_length=service.NAME_MAX)
    manufacturer: str | None = Field(default=None, max_length=service.NAME_MAX)
    part_number: str | None = Field(default=None, max_length=service.PART_MAX)
    price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    tax: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    gl_code: str | None = Field(default=None, max_length=service.GL_MAX)
    hide_from_purchase_orders: bool = False
    depreciation_method: AssetDepreciationMethod | None = None
    useful_life_years: int | None = Field(default=None, ge=1, le=100)
    salvage_value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    description: str | None = Field(default=None, max_length=service.TEXT_MAX)


class AssetProductPatch(BaseModel):
    """Product fields to change (only those sent; null clears an optional one)."""

    model_config = ConfigDict(extra="forbid")

    product_type_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=service.NAME_MAX)
    manufacturer: str | None = Field(default=None, max_length=service.NAME_MAX)
    part_number: str | None = Field(default=None, max_length=service.PART_MAX)
    price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    tax: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    gl_code: str | None = Field(default=None, max_length=service.GL_MAX)
    hide_from_purchase_orders: bool | None = None
    depreciation_method: AssetDepreciationMethod | None = None
    useful_life_years: int | None = Field(default=None, ge=1, le=100)
    salvage_value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    description: str | None = Field(default=None, max_length=service.TEXT_MAX)


_REQUIRED_PRODUCT_FIELDS = {"product_type_id", "name", "hide_from_purchase_orders"}


@router.get("/products", summary="Products")
async def list_products(
    session: TenantSession, query: ProductsQuery, subject: View
) -> Page[AssetProductOut]:
    """Products, filtered (`product_type_id=`, `manufacturer=`, the DSL) and paged."""
    del subject
    await service.ensure_defaults(session)
    page = await paginate(session, service.products_query(), query)
    return Page[AssetProductOut](
        items=[AssetProductOut.of(row) for row in page.rows],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        estimated_total=page.estimated_total,
    )


@router.post(
    "/products",
    summary="Add a product",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetProductOut,
    dependencies=[audited("asset.product_saved", object_type="asset_product")],
)
async def create_product(
    body: AssetProductIn,
    session: TenantSession,
    subject: Configure,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """A new product. Send an Idempotency-Key."""

    async def run() -> Created:
        row = await service.create_product(
            session, subject, body.model_dump(exclude_none=True), source=source_of(request)
        )
        return Created(body=AssetProductOut.of(row), headers={"ETag": f'"{row.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get(
    "/products/{product_id}",
    summary="Get a product",
    responses={404: {"model": ProblemDetail, "description": "asset_product_not_found"}},
)
async def get_product(
    product_id: uuid.UUID, session: TenantSession, subject: View, response: Response
) -> AssetProductOut:
    """One product."""
    del subject
    row = await service.get_product(session, product_id)
    set_etag(response, row.version)
    return AssetProductOut.of(row)


@router.patch(
    "/products/{product_id}",
    summary="Change a product",
    responses=WRITE,
    dependencies=[
        audited("asset.product_saved", object_type="asset_product", object_param="product_id")
    ],
)
async def patch_product(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    product_id: uuid.UUID,
    body: AssetProductPatch,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AssetProductOut:
    """Change the fields sent (If-Match). Assets keep the cost they were bought at."""
    sent = body.model_dump(include=body.model_fields_set)
    values = {k: v for k, v in sent.items() if v is not None or k not in _REQUIRED_PRODUCT_FIELDS}
    row = await service.update_product(
        session, subject, product_id, values, expected_version=version, source=source_of(request)
    )
    set_etag(response, row.version)
    return AssetProductOut.of(row)


@router.delete(
    "/products/{product_id}",
    summary="Delete a product",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
    dependencies=[
        audited("asset.product_deleted", object_type="asset_product", object_param="product_id")
    ],
)
async def delete_product(
    product_id: uuid.UUID,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
    request: Request,
) -> None:
    """Moves it to the trash."""
    await service.delete_product(
        session, subject, product_id, expected_version=version, source=source_of(request)
    )


# --- what a person or department holds (REQ-AST-019 AC2, 020) -------------------------------
# A fixed path, so here: the records router's /assets/{asset_id} would take it otherwise.


@router.get("/held-by", summary="The assets a person or department holds, or held")
async def held_by(
    session: TenantSession,
    subject: Annotated[Subject, Depends(require_permission("assets.view"))],
    kind: Annotated[Literal["user", "department"], Query()],
    holder_id: Annotated[uuid.UUID, Query(alias="id")],
    current: Annotated[bool, Query(description="Only what they hold now.")] = False,  # noqa: FBT002 - a query flag (FastAPI)
) -> list[HeldAssetOut]:
    """Newest first, within what you may see; `current` keeps only the open holdings."""
    found = await ownership.held_by(session, subject, ownership.Holder(kind, holder_id))
    return [
        HeldAssetOut(asset=AssetOut.of(asset), holding=AssetHoldingOut.of(holding))
        for asset, holding in found
        if not current or holding.ended_at is None
    ]


# --- my assets and acknowledgements (REQ-AST-023, 024) ---------------------------------------
# For whoever is signed in, requesters included: what they hold needs no asset permission.

SignedIn = Annotated[Subject, Depends(require_signed_in())]


class AcknowledgementOut(BaseModel):
    """A person's acknowledgement of an asset given to them."""

    id: uuid.UUID
    status: Literal["pending", "accepted", "disputed"]
    comment: str | None
    channel: str | None
    answered_at: datetime | None
    asked_at: datetime


class MyAssetOut(BaseModel):
    """An asset the person holds, or their department does (`through_department`)."""

    id: uuid.UUID
    tag: str | None
    name: str
    product_type_id: uuid.UUID
    state_id: uuid.UUID
    through_department: bool
    acknowledgement: AcknowledgementOut | None


class AcknowledgementAnswerIn(BaseModel):
    """Accept, or dispute with a comment saying what is wrong."""

    model_config = ConfigDict(extra="forbid")

    accept: bool
    comment: str | None = Field(default=None, max_length=2000)
    channel: Literal["portal", "console"] = "portal"


def _ack_out(row: AssetAcknowledgement) -> AcknowledgementOut:
    return AcknowledgementOut(
        id=row.id,
        # The table's check holds it to these three.
        status=cast("Literal['pending', 'accepted', 'disputed']", row.status),
        comment=row.comment,
        channel=row.channel,
        answered_at=row.answered_at,
        asked_at=row.created_at,
    )


@router.get("/mine", summary="The assets I hold")
async def my_assets(session: TenantSession, subject: SignedIn) -> list[MyAssetOut]:
    """Mine, and my department's when the organisation shows them; live (REQ-AST-024)."""
    return [
        MyAssetOut(
            id=m.asset.id,
            tag=m.asset.tag,
            name=m.asset.name,
            product_type_id=m.asset.product_type_id,
            state_id=m.asset.state_id,
            through_department=m.through_department,
            acknowledgement=None if m.acknowledgement is None else _ack_out(m.acknowledgement),
        )
        for m in await acknowledgements.mine(session, subject)
    ]


@router.post(
    "/acknowledgements/{acknowledgement_id}/answer",
    summary="Accept or dispute an asset given to me",
    responses={
        404: {"model": ProblemDetail, "description": "asset_acknowledgement_not_found"},
        409: {"model": ProblemDetail, "description": "asset_acknowledgement_answered"},
    },
)
async def answer_acknowledgement(
    acknowledgement_id: uuid.UUID,
    body: AcknowledgementAnswerIn,
    session: TenantSession,
    subject: SignedIn,
) -> AcknowledgementOut:
    """Only my own, only once. A dispute tells the person who gave it to me (AC3)."""
    row = await acknowledgements.answer(
        session,
        subject,
        acknowledgement_id,
        accept=body.accept,
        comment=body.comment,
        channel=body.channel,
    )
    return _ack_out(row)
