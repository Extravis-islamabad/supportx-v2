"""Assets HTTP API under /api/v1/assets (WP-049a session 1: the catalogue). No business logic.

Reading the catalogue needs `assets.view` (the asset form uses it); changing it needs
`config.assets` or `settings.manage`. Writes use If-Match; creates take an Idempotency-Key.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.assets.domain.catalogue import (
    AgeBasis,
    DepreciationMethod,
    StateCategory,
    TypeCategory,
    TypeKind,
)
from app.modules.assets.infra.models import (
    AssetLifeCycleTransition,
    AssetProduct,
    AssetProductType,
    AssetSettings,
    AssetState,
)
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


class SettingsOut(BaseModel):
    """The tenant's asset settings (Appendix A defaults until an admin changes them)."""

    tag_pattern: str
    age_basis: AgeBasis
    cost_includes_tax: bool = Field(description="D-141: an asset's cost includes its tax.")
    copy_limit: int
    site_follows_owner: bool
    portal_own_assets_only: bool
    email_include_assets: bool
    scan_retention_months: int
    version: int

    @classmethod
    def of(cls, row: AssetSettings) -> "SettingsOut":
        """From the row."""
        return cls(
            tag_pattern=row.tag_pattern,
            age_basis=AgeBasis(row.age_basis),
            cost_includes_tax=row.cost_includes_tax,
            copy_limit=row.copy_limit,
            site_follows_owner=row.site_follows_owner,
            portal_own_assets_only=row.portal_own_assets_only,
            email_include_assets=row.email_include_assets,
            scan_retention_months=row.scan_retention_months,
            version=row.version,
        )


class SettingsIn(BaseModel):
    """Settings to change (only those sent)."""

    model_config = ConfigDict(extra="forbid")

    tag_pattern: str | None = Field(default=None, max_length=40, description="e.g. AST-{n}")
    age_basis: AgeBasis | None = None
    cost_includes_tax: bool | None = None
    copy_limit: int | None = Field(default=None, ge=1, le=500)
    site_follows_owner: bool | None = None
    portal_own_assets_only: bool | None = None
    email_include_assets: bool | None = None
    scan_retention_months: int | None = Field(default=None, ge=1, le=60)


@router.get("/settings", summary="Asset settings")
async def get_settings(session: TenantSession, subject: View, response: Response) -> SettingsOut:
    """The tenant's asset settings."""
    del subject
    row = await service.get_settings(session)
    set_etag(response, row.version)
    return SettingsOut.of(row)


@router.patch(
    "/settings",
    summary="Change asset settings",
    responses=WRITE,
    dependencies=[audited("asset.settings_changed", object_type="asset_settings")],
)
async def patch_settings(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: SettingsIn,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> SettingsOut:
    """Change the settings sent. If-Match: the version you read."""
    row = await service.update_settings(
        session,
        subject,
        body.model_dump(include=body.model_fields_set, exclude_none=True),
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, row.version)
    return SettingsOut.of(row)


# --- states -----------------------------------------------------------------------------------


class StateOut(BaseModel):
    """An asset state; `category` is its fixed meaning (REQ-AST-012)."""

    id: uuid.UUID
    code: str
    names: Names
    category: StateCategory
    reason_required: bool
    is_default_for_category: bool
    system: bool = Field(description="Used by loans or disposal: it can be renamed, not deleted.")
    sort: int
    version: int

    @classmethod
    def of(cls, row: AssetState) -> "StateOut":
        """From the row."""
        return cls(
            id=row.id,
            code=row.code,
            names=row.names,
            category=StateCategory(row.category),
            reason_required=row.reason_required,
            is_default_for_category=row.is_default_for_category,
            system=row.system,
            sort=row.sort,
            version=row.version,
        )


class StateIn(BaseModel):
    """A new state."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(max_length=40, description="Stable lowercase code, e.g. with_courier.")
    names: Names = Field(description=NAMES_DOC)
    category: StateCategory
    reason_required: bool = False
    is_default_for_category: bool = False


class StatePatch(BaseModel):
    """State fields to change (only those sent)."""

    model_config = ConfigDict(extra="forbid")

    names: Names | None = Field(default=None, description=NAMES_DOC)
    category: StateCategory | None = None
    reason_required: bool | None = None
    is_default_for_category: bool | None = None
    sort: int | None = Field(default=None, ge=0, le=10_000)


@router.get("/states", summary="Asset states")
async def list_states(session: TenantSession, subject: View) -> list[StateOut]:
    """Every state, in order."""
    del subject
    return [StateOut.of(s) for s in await service.list_states(session)]


@router.post(
    "/states",
    summary="Add an asset state",
    status_code=status.HTTP_201_CREATED,
    response_model=StateOut,
    dependencies=[audited("asset.state_saved", object_type="asset_state")],
)
async def create_state(
    body: StateIn,
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
        return Created(body=StateOut.of(row), headers={"ETag": f'"{row.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/states/{state_id}",
    summary="Change an asset state",
    responses=WRITE,
    dependencies=[audited("asset.state_saved", object_type="asset_state", object_param="state_id")],
)
async def patch_state(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    state_id: uuid.UUID,
    body: StatePatch,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> StateOut:
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
    return StateOut.of(row)


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


class MoveIO(BaseModel):
    """One allowed move between two states."""

    model_config = ConfigDict(extra="forbid")

    from_state_id: uuid.UUID
    to_state_id: uuid.UUID
    reason_required: bool = False
    permission: str | None = Field(
        default=None, max_length=80, description="A permission the move needs, if any."
    )

    @classmethod
    def of(cls, row: AssetLifeCycleTransition) -> "MoveIO":
        """From the row."""
        return cls(
            from_state_id=row.from_state_id,
            to_state_id=row.to_state_id,
            reason_required=row.reason_required,
            permission=row.permission,
        )


class LifeCycleOut(BaseModel):
    """A life cycle and its moves (REQ-AST-013)."""

    id: uuid.UUID
    names: Names
    is_default: bool
    moves: list[MoveIO]
    version: int

    @classmethod
    def of(cls, view: service.LifeCycleView) -> "LifeCycleOut":
        """From the service's view."""
        return cls(
            id=view.record.id,
            names=view.record.names,
            is_default=view.record.is_default,
            moves=[MoveIO.of(m) for m in view.moves],
            version=view.record.version,
        )


class LifeCycleIn(BaseModel):
    """A new life cycle."""

    model_config = ConfigDict(extra="forbid")

    names: Names = Field(description=NAMES_DOC)
    moves: list[MoveIO] = Field(default_factory=list, max_length=500)


class LifeCyclePatch(BaseModel):
    """Life cycle fields to change; `moves` replaces every move."""

    model_config = ConfigDict(extra="forbid")

    names: Names | None = Field(default=None, description=NAMES_DOC)
    moves: list[MoveIO] | None = Field(default=None, max_length=500)
    is_default: bool | None = None


@router.get("/life-cycles", summary="Asset life cycles")
async def list_life_cycles(session: TenantSession, subject: View) -> list[LifeCycleOut]:
    """Every life cycle with its moves, the default first."""
    del subject
    return [LifeCycleOut.of(v) for v in await service.list_life_cycles(session)]


@router.post(
    "/life-cycles",
    summary="Add an asset life cycle",
    status_code=status.HTTP_201_CREATED,
    response_model=LifeCycleOut,
    dependencies=[audited("asset.life_cycle_saved", object_type="asset_life_cycle")],
)
async def create_life_cycle(
    body: LifeCycleIn,
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
        return Created(body=LifeCycleOut.of(view), headers={"ETag": f'"{view.record.version}"'})

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
    body: LifeCyclePatch,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> LifeCycleOut:
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
    return LifeCycleOut.of(view)


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


class ProductTypeOut(BaseModel):
    """A node of the product type tree (REQ-AST-003)."""

    id: uuid.UUID
    parent_id: uuid.UUID | None
    api_name: str = Field(description="For integrations; never shown to end users.")
    names: Names
    icon: str | None
    category: TypeCategory = Field(description="D-141: only IT assets count toward the limit.")
    kind: TypeKind
    description: str | None
    life_cycle_id: uuid.UUID | None = Field(description="None: the default life cycle.")
    tag_pattern: str | None = Field(description="None: the tenant's pattern.")
    ack_required: bool
    sort: int
    version: int

    @classmethod
    def of(cls, row: AssetProductType) -> "ProductTypeOut":
        """From the row."""
        return cls(
            id=row.id,
            parent_id=row.parent_id,
            api_name=row.api_name,
            names=row.names,
            icon=row.icon,
            category=TypeCategory(row.category),
            kind=TypeKind(row.kind),
            description=row.description,
            life_cycle_id=row.life_cycle_id,
            tag_pattern=row.tag_pattern,
            ack_required=row.ack_required,
            sort=row.sort,
            version=row.version,
        )


class ProductTypeIn(BaseModel):
    """A new type; under a parent it takes the parent's category and kind."""

    model_config = ConfigDict(extra="forbid")

    api_name: str = Field(max_length=64)
    names: Names = Field(description=NAMES_DOC)
    parent_id: uuid.UUID | None = None
    icon: str | None = Field(default=None, max_length=40)
    category: TypeCategory | None = Field(default=None, description="Top-level types only.")
    kind: TypeKind | None = Field(default=None, description="Top-level types only.")
    description: str | None = Field(default=None, max_length=service.TEXT_MAX)
    life_cycle_id: uuid.UUID | None = None
    tag_pattern: str | None = Field(default=None, max_length=40)
    ack_required: bool = False


class ProductTypePatch(BaseModel):
    """Type fields to change (only those sent; null clears an optional one)."""

    model_config = ConfigDict(extra="forbid")

    names: Names | None = Field(default=None, description=NAMES_DOC)
    parent_id: uuid.UUID | None = None
    icon: str | None = Field(default=None, max_length=40)
    category: TypeCategory | None = None
    kind: TypeKind | None = None
    description: str | None = Field(default=None, max_length=service.TEXT_MAX)
    life_cycle_id: uuid.UUID | None = None
    tag_pattern: str | None = Field(default=None, max_length=40)
    ack_required: bool | None = None
    sort: int | None = Field(default=None, ge=0, le=10_000)


@router.get("/product-types", summary="Product types")
async def list_product_types(session: TenantSession, subject: View) -> list[ProductTypeOut]:
    """The whole tree, flat: each type names its parent."""
    del subject
    return [ProductTypeOut.of(t) for t in await service.list_product_types(session)]


@router.post(
    "/product-types",
    summary="Add a product type",
    status_code=status.HTTP_201_CREATED,
    response_model=ProductTypeOut,
    dependencies=[audited("asset.product_type_saved", object_type="asset_product_type")],
)
async def create_product_type(
    body: ProductTypeIn,
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
        return Created(body=ProductTypeOut.of(row), headers={"ETag": f'"{row.version}"'})

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
    body: ProductTypePatch,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> ProductTypeOut:
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
    return ProductTypeOut.of(row)


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


class ProductOut(BaseModel):
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
    depreciation_method: DepreciationMethod | None
    useful_life_years: int | None
    salvage_value: Decimal | None
    description: str | None
    updated_at: datetime
    version: int

    @classmethod
    def of(cls, row: AssetProduct) -> "ProductOut":
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
                DepreciationMethod(row.depreciation_method) if row.depreciation_method else None
            ),
            useful_life_years=row.useful_life_years,
            salvage_value=row.salvage_value,
            description=row.description,
            updated_at=row.updated_at,
            version=row.version,
        )


class ProductIn(BaseModel):
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
    depreciation_method: DepreciationMethod | None = None
    useful_life_years: int | None = Field(default=None, ge=1, le=100)
    salvage_value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    description: str | None = Field(default=None, max_length=service.TEXT_MAX)


class ProductPatch(BaseModel):
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
    depreciation_method: DepreciationMethod | None = None
    useful_life_years: int | None = Field(default=None, ge=1, le=100)
    salvage_value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    description: str | None = Field(default=None, max_length=service.TEXT_MAX)


_REQUIRED_PRODUCT_FIELDS = {"product_type_id", "name", "hide_from_purchase_orders"}


@router.get("/products", summary="Products")
async def list_products(
    session: TenantSession, query: ProductsQuery, subject: View
) -> Page[ProductOut]:
    """Products, filtered (`product_type_id=`, `manufacturer=`, the DSL) and paged."""
    del subject
    await service.ensure_defaults(session)
    page = await paginate(session, service.products_query(), query)
    return Page[ProductOut](
        items=[ProductOut.of(row) for row in page.rows],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        estimated_total=page.estimated_total,
    )


@router.post(
    "/products",
    summary="Add a product",
    status_code=status.HTTP_201_CREATED,
    response_model=ProductOut,
    dependencies=[audited("asset.product_saved", object_type="asset_product")],
)
async def create_product(
    body: ProductIn,
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
        return Created(body=ProductOut.of(row), headers={"ETag": f'"{row.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get(
    "/products/{product_id}",
    summary="Get a product",
    responses={404: {"model": ProblemDetail, "description": "asset_product_not_found"}},
)
async def get_product(
    product_id: uuid.UUID, session: TenantSession, subject: View, response: Response
) -> ProductOut:
    """One product."""
    del subject
    row = await service.get_product(session, product_id)
    set_etag(response, row.version)
    return ProductOut.of(row)


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
    body: ProductPatch,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> ProductOut:
    """Change the fields sent (If-Match). Assets keep the cost they were bought at."""
    sent = body.model_dump(include=body.model_fields_set)
    values = {k: v for k, v in sent.items() if v is not None or k not in _REQUIRED_PRODUCT_FIELDS}
    row = await service.update_product(
        session, subject, product_id, values, expected_version=version, source=source_of(request)
    )
    set_etag(response, row.version)
    return ProductOut.of(row)


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
