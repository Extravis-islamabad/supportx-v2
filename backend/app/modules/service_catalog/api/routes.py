"""The service catalog over HTTP (WP-030 s1, WP-031 s1; plan D1..D13).

GET    /api/v1/catalog/categories              categories (requesters: the ones they may browse)
POST   /api/v1/catalog/categories              add one (catalog_items.manage), Idempotency-Key
PATCH  /api/v1/catalog/categories/{id}         change it (If-Match)
DELETE /api/v1/catalog/categories/{id}         delete an empty one (If-Match; 409 with counts)
GET    /api/v1/catalog/items                   what the viewer may see (filters: category, status)
GET    /api/v1/catalog/items/search?q=         search them (names, keywords, texts, typos)
GET    /api/v1/catalog/items/{id}              one item
POST   /api/v1/catalog/items                   add one (a draft unless published at once)
PATCH  /api/v1/catalog/items/{id}              change it, publish or retire it (If-Match)
POST   /api/v1/catalog/items/{id}/copy         an independent draft copy, Idempotency-Key
DELETE /api/v1/catalog/items/{id}              delete one no request names (If-Match; else 409)
GET    /api/v1/catalog/settings                the tenant's catalog settings
PATCH  /api/v1/catalog/settings                change them (If-Match)
GET    /api/v1/catalog/starter                 how many starter items are still drafts
POST   /api/v1/catalog/starter/publish         choose their group and publish them (D-138)
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import Subject
from app.modules.service_catalog.domain.catalog import ItemKind, ItemStatus
from app.modules.service_catalog.domain.items import (
    ApproverKind,
    EscalationTarget,
    ItemAudience,
    QuestionAudience,
    QuestionKind,
    RestartOn,
    StageRule,
)
from app.modules.service_catalog.domain.pricing import ChargeTo, PricePeriod
from app.modules.service_catalog.infra.models import CatalogSettings, ServiceCategory
from app.modules.service_catalog.service import catalog as service
from app.modules.service_catalog.service import categories, search, settings, starter
from app.modules.service_catalog.service.common import is_staff
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

SignedIn = Annotated[Subject, Depends(require_signed_in())]

router = APIRouter(
    prefix="/catalog", tags=["catalog"], dependencies=[Depends(rate_limit("catalog"))]
)

# Any in the models below: a question's default is a JSON value of the question's own kind.


class QuestionIO(BaseModel):
    """A form question."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(max_length=40)
    label: dict[str, str]
    kind: QuestionKind
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=50)
    option_labels: dict[str, dict[str, str]] = Field(default_factory=dict)
    # WP-047b S1 (REQ-CAT-020): a choice's extra price per option (amounts as decimal text).
    option_prices: dict[str, str] = Field(default_factory=dict, max_length=50)
    help: dict[str, str] = Field(default_factory=dict)
    default: Any = None
    shown_to: list[QuestionAudience] = Field(default_factory=lambda: list(QuestionAudience))
    restarts_approval: bool = Field(
        default=False,
        description="A change to this answer after submitting restarts approval (REQ-SR-041).",
    )


class ApproverIO(BaseModel):
    """An approver: a kind, and the person, group or question it names (REQ-SR-022, -031)."""

    model_config = ConfigDict(extra="forbid")

    kind: ApproverKind
    person_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = Field(default=None, description="`group` only.")
    question_key: str | None = Field(
        default=None, max_length=40, description="`person_answer` only: a person question."
    )


class AutoRuleIO(BaseModel):
    """A rule that approves a stage automatically (WP-047a S2b; REQ-SR-033)."""

    model_config = ConfigDict(extra="forbid")

    name: dict[str, str] = Field(
        description="Shown on the record as the reason, per language (English required)."
    )
    condition: dict[str, Any] = Field(
        description="The form rules' condition language over the answers, `quantity` and "
        "`requester_groups` (`eq` a group ID: the requester is a member)."
    )


class ApprovalStageIO(BaseModel):
    """One approval stage (WP-047a S2a; REQ-SR-029..032)."""

    model_config = ConfigDict(extra="forbid")

    approvers: list[ApproverIO] = Field(max_length=10)  # required as before S2a (additive API)
    backup_id: uuid.UUID | None = None
    comments_required: bool = False
    self_approval: bool = False
    rule: StageRule = Field(
        default=StageRule.ANY, description="any (the first decision), all, majority."
    )
    parallel_group: str | None = Field(
        default=None,
        max_length=40,
        description="Stages with the same group open together (REQ-SR-030).",
    )
    condition: dict[str, Any] | None = Field(
        default=None,
        description="The stage applies only when this holds (REQ-SR-032): the form rules' "
        "condition language over the answers and `quantity`.",
    )
    auto_earlier: bool | None = Field(
        default=None,
        description="Someone who approved an earlier stage of the same request is not asked "
        "again (REQ-SR-033); null: the tenant's setting decides. Professional.",
    )
    auto_rules: list[AutoRuleIO] = Field(
        default_factory=list,
        max_length=5,
        description="Rules that approve the stage at once when one holds (REQ-SR-033). "
        "Professional.",
    )
    escalate_to: EscalationTarget = Field(
        default=EscalationTarget.BACKUP,
        description="Where a pending approval goes after its last reminder (REQ-SR-034): the "
        "backup, the approver's manager, the request's group, or none. The approver keeps it too.",
    )


class ApprovalIO(ApprovalStageIO):
    """The item's approval: one stage (as before), or `stages` in order (Professional)."""

    stages: list[ApprovalStageIO] | None = Field(
        default=None,
        max_length=10,
        description="Every stage in order (WP-047a S2a). When given, the top-level stage "
        "fields are ignored on save; on read they repeat the first stage.",
    )
    restart_on: list[RestartOn] = Field(
        default_factory=list,
        description="The request's own values whose change restarts approval (REQ-SR-041): "
        "quantity, requested_for. Marked questions restart it too.",
    )

    @classmethod
    def read(cls, stored: dict[str, Any] | None) -> "ApprovalIO | None":
        """From the stored JSON: the old single stage, or `stages` with stage 1 on top."""
        if not stored:
            return None
        if "stages" not in stored:
            return cls.model_validate(stored)
        stages = stored["stages"] or []
        first = dict(stages[0]) if stages else {}
        extra = {"restart_on": stored["restart_on"]} if stored.get("restart_on") else {}
        return cls.model_validate({**first, "stages": stages, **extra})


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
    summaries: dict[str, str] | None = None
    descriptions: dict[str, str] | None = Field(
        default=None, description="Rich text per language; sanitised on the server."
    )
    keywords: dict[str, list[str]] | None = None
    icon: str | None = Field(default=None, max_length=40)
    category_id: uuid.UUID | None = None
    extra_category_ids: list[uuid.UUID] | None = Field(default=None, max_length=5)
    kind: ItemKind | None = None
    template_id: uuid.UUID | None = None
    audience: ItemAudience | None = None
    status: ItemStatus | None = Field(
        default=None, description="draft → published → retired → published (plan D3)."
    )
    enabled: bool | None = Field(
        default=None, deprecated=True, description="Use status: true publishes, false retires."
    )
    publish_at: datetime | None = None
    retire_at: datetime | None = None
    owner_id: uuid.UUID | None = None
    featured: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100_000)
    subject_template: str | None = Field(default=None, max_length=200)
    requesters_see_approval: bool | None = None
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
    # WP-047a S1: REQ-SR-014 (Professional: `catalog`) and REQ-SR-015.
    max_quantity: int | None = Field(default=None, ge=1, le=10_000)
    asks_needed_by: bool | None = None
    # WP-047b S1 (REQ-CAT-020, -021; Professional): base currency only (D-164).
    price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    price_period: PricePeriod | None = None
    internal_cost: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    charge_to: ChargeTo | None = None
    charge_question_key: str | None = Field(default=None, max_length=40)


class CatalogMissingTranslation(BaseModel):
    """A text with English but nothing in one of the tenant's languages (plan D5)."""

    field: str
    language: str


class ExpectedDeliveryOut(BaseModel):
    """How long a request usually takes: "Usually delivered within N working days" (Haider)."""

    amount: int
    unit: str = Field(description="minutes, hours or business_days.")
    around_the_clock: bool = Field(description="False: counted in working time.")
    at: datetime | None = Field(
        default=None,
        description="When a request raised now should be delivered (REQ-SR-015 AC1), on the "
        "SLA's calendar; the form shows it in the requester's time zone.",
    )


class CatalogItemOut(BaseModel):
    """An item as screens show it; staff see the whole item, others what they raise it with."""

    id: uuid.UUID
    names: dict[str, str]
    summaries: dict[str, str]
    descriptions: dict[str, str]
    keywords: dict[str, list[str]]
    icon: str | None
    category_id: uuid.UUID | None
    extra_category_ids: list[uuid.UUID]
    kind: ItemKind
    template_id: uuid.UUID | None
    audience: ItemAudience
    status: ItemStatus
    enabled: bool = Field(
        description="True when the item is published (WP-030 clients; read status)."
    )
    publish_at: datetime | None
    retire_at: datetime | None
    published_at: datetime | None
    owner_id: uuid.UUID | None
    featured: bool
    sort_order: int
    subject_template: str | None
    requesters_see_approval: bool
    starter: bool
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
    max_quantity: int | None = Field(
        default=None, description="The most one request may ask for; null: no quantity asked."
    )
    asks_needed_by: bool = False
    # WP-047b S1: to staff, and to requesters only when the tenant shows prices (D-184).
    price: Decimal | None = None
    price_period: PricePeriod = PricePeriod.ONCE
    internal_cost: Decimal | None = Field(default=None, description="Staff only.")
    charge_to: ChargeTo = ChargeTo.REQUESTED_FOR_DEPARTMENT
    charge_question_key: str | None = None
    missing_translations: list[CatalogMissingTranslation]
    can_manage: bool
    version: int
    expected_delivery: ExpectedDeliveryOut | None = Field(
        default=None,
        description="One item's read only: how long a request usually takes, from the SLA "
        "that would apply (null: no SLA applies, so nothing is said).",
    )

    @classmethod
    def of(
        cls,
        view: service.ItemView,
        *,
        staff: bool,
        quantity_offered: bool = True,
        prices_shown: bool = True,
    ) -> "CatalogItemOut":
        """From the service's view; requesters never see questions meant for others.

        `quantity_offered` false: no quantity is offered (REQ-SR-014 is Professional), so the
        portal never shows a field the server would refuse (lane C, #578).
        """
        item = view.item
        questions = [
            q
            for q in item.questions
            if staff
            or QuestionAudience.REQUESTER.value
            in (q.get("shown_to") or [QuestionAudience.REQUESTER])
        ]
        fields = {name: getattr(item, name) for name in service.ITEM_FIELDS}
        if not quantity_offered:
            fields["max_quantity"] = None
        if not staff:  # an internal cost is the desk's, never a requester's (REQ-CAT-020)
            fields["internal_cost"] = None
            fields["charge_to"] = ChargeTo.REQUESTED_FOR_DEPARTMENT.value
            fields["charge_question_key"] = None
        if not prices_shown:  # D-184: requesters see prices only when the tenant shows them
            fields["price"] = None
            questions = [{k: v for k, v in q.items() if k != "option_prices"} for q in questions]
        return cls.model_validate(
            {
                **fields,
                "approval": ApprovalIO.read(item.approval),
                "questions": questions,
                "id": item.id,
                "status": item.status,
                "enabled": item.status == ItemStatus.PUBLISHED.value,
                "published_at": item.published_at,
                "starter": item.starter,
                "missing_translations": [
                    {"field": at, "language": lang} for at, lang in view.missing_translations
                ],
                "can_manage": view.can_manage,
                "version": item.version,
            }
        )


class CategoryIn(BaseModel):
    """A new category (the WP-030 contract, plus the tree's fields)."""

    model_config = ConfigDict(extra="forbid")

    names: dict[str, str]
    sort_order: int = Field(default=0, ge=0, le=10_000)
    descriptions: dict[str, str] | None = None
    parent_id: uuid.UUID | None = None
    icon: str | None = Field(default=None, max_length=40)
    enabled: bool | None = None


class CategoryPatchIn(BaseModel):
    """A change to a category (only what is sent changes)."""

    model_config = ConfigDict(extra="forbid")

    names: dict[str, str] | None = None
    descriptions: dict[str, str] | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)
    parent_id: uuid.UUID | None = None
    icon: str | None = Field(default=None, max_length=40)
    enabled: bool | None = None


class CategoryOut(BaseModel):
    """A category."""

    id: uuid.UUID
    names: dict[str, str]
    descriptions: dict[str, str]
    sort_order: int
    parent_id: uuid.UUID | None
    icon: str | None
    enabled: bool
    version: int

    @classmethod
    def of(cls, row: ServiceCategory) -> "CategoryOut":
        """From the row."""
        return cls(
            id=row.id,
            names=row.names,
            descriptions=row.descriptions,
            sort_order=row.sort_order,
            parent_id=row.parent_id,
            icon=row.icon,
            enabled=row.enabled,
            version=row.version,
        )


class CatalogSettingsIn(BaseModel):
    """The tenant's catalog settings."""

    model_config = ConfigDict(extra="forbid")

    hide_default_incident_template: bool | None = None
    requesters_see_prices: bool | None = None  # WP-047b S1 (D-184), off by default


class CatalogSettingsOut(BaseModel):
    """The tenant's catalog settings."""

    hide_default_incident_template: bool
    requesters_see_prices: bool = False
    version: int

    @classmethod
    def of(cls, row: CatalogSettings) -> "CatalogSettingsOut":
        """From the row (or the defaults)."""
        return cls(
            hide_default_incident_template=row.hide_default_incident_template,
            requesters_see_prices=row.requesters_see_prices,
            version=row.version,
        )


class CatalogStarterOut(BaseModel):
    """The starter catalog's drafts still waiting for a group (D-138)."""

    drafts: int


class CatalogStarterPublishIn(BaseModel):
    """The fulfilment group the starter drafts get."""

    model_config = ConfigDict(extra="forbid")

    group_id: uuid.UUID


class CatalogStarterPublishOut(BaseModel):
    """How many were published, and which still need work before they can be."""

    published: int
    skipped: list[uuid.UUID]


def _fields(body: BaseModel) -> dict[str, Any]:
    return body.model_dump(mode="json", include=body.model_fields_set)


# --- categories -----------------------------------------------------------------------------------


@router.get("/categories", summary="Catalog categories")
async def list_categories(session: TenantSession, subject: SignedIn) -> list[CategoryOut]:
    """Every category, in their order (requesters: the ones they may browse)."""
    return [CategoryOut.of(c) for c in await categories.list_categories(session, subject)]


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
    """A new category, at the root or under a parent. Send an Idempotency-Key."""

    async def run() -> Created:
        row = await categories.create_category(
            session, subject, _fields(body), source=source_of(request)
        )
        return Created(body=CategoryOut.of(row), headers={"ETag": f'"{row.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/categories/{category_id}",
    summary="Change a catalog category",
    dependencies=[
        audited(
            "catalog.category_changed", object_type="service_category", object_param="category_id"
        )
    ],
)
async def update_category(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    category_id: uuid.UUID,
    body: CategoryPatchIn,
    version: ExpectedVersion,
    session: TenantSession,
    subject: SignedIn,
    request: Request,
    response: Response,
) -> CategoryOut:
    """Change what is sent; If-Match with the version read."""
    row = await categories.update_category(
        session,
        subject,
        category_id,
        expected_version=version,
        values=_fields(body),
        source=source_of(request),
    )
    set_etag(response, row.version)
    return CategoryOut.of(row)


@router.delete(
    "/categories/{category_id}",
    summary="Delete an empty catalog category",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        audited(
            "catalog.category_deleted", object_type="service_category", object_param="category_id"
        )
    ],
)
async def delete_category(
    category_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: SignedIn,
    request: Request,
) -> Response:
    """Only while it holds no items or categories (409 with the counts otherwise)."""
    await categories.delete_category(
        session, subject, category_id, expected_version=version, source=source_of(request)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- items ----------------------------------------------------------------------------------------


@router.get("/items", summary="Catalog items you may see")
async def list_items(
    session: TenantSession,
    subject: SignedIn,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    item_status: Annotated[list[ItemStatus] | None, Query(alias="status")] = None,
    featured: Annotated[bool | None, Query()] = None,
) -> list[CatalogItemOut]:
    """Staff see every item in any status; others the published items open to them."""
    staff = is_staff(subject)
    views = await service.list_items(
        session,
        subject,
        category_id=category_id,
        statuses=item_status or (),
        featured=featured,
    )
    offered, prices = await _shown(session, subject, staff=staff)
    return [
        CatalogItemOut.of(v, staff=staff, quantity_offered=offered, prices_shown=prices)
        for v in views
    ]


async def _shown(session: AsyncSession, subject: Subject, *, staff: bool) -> tuple[bool, bool]:
    """(a quantity is offered, prices are shown) for this person (REQ-SR-014; D-184)."""
    if staff:
        return True, True
    licensed = await service.quantity_licensed(subject)  # both are the catalog feature
    return licensed, licensed and (await settings.read(session)).requesters_see_prices


@router.get("/items/popular", summary="The most requested catalog items you may see")
async def popular_items(
    session: TenantSession,
    subject: SignedIn,
    limit: Annotated[int, Query(ge=1, le=20)] = 6,
) -> list[CatalogItemOut]:
    """Most requested over the last 90 days first (REQ-CAT-027, the portal home, WP-032)."""
    staff = is_staff(subject)
    views = await service.popular_items(session, subject, limit=limit)
    offered, prices = await _shown(session, subject, staff=staff)
    return [
        CatalogItemOut.of(v, staff=staff, quantity_offered=offered, prices_shown=prices)
        for v in views
    ]


@router.get("/items/search", summary="Search the catalog items you may see")
async def search_items(
    session: TenantSession,
    subject: SignedIn,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[CatalogItemOut]:
    """Names, keywords, summaries and descriptions in every language; best match first."""
    staff = is_staff(subject)
    offered, prices = await _shown(session, subject, staff=staff)
    return [
        CatalogItemOut.of(v, staff=staff, quantity_offered=offered, prices_shown=prices)
        for v in await search.search_items(session, subject, q, limit=limit)
    ]


@router.get("/items/{item_id}", summary="One catalog item")
async def get_item(
    item_id: uuid.UUID, session: TenantSession, subject: SignedIn, response: Response
) -> CatalogItemOut:
    """One item you may see (404 otherwise)."""
    view = await service.get_item(session, subject, item_id)
    set_etag(response, view.item.version)
    staff = is_staff(subject)
    offered, prices = await _shown(session, subject, staff=staff)
    out = CatalogItemOut.of(view, staff=staff, quantity_offered=offered, prices_shown=prices)
    target = await service.expected_delivery(session, view.item)
    if target is not None:
        out.expected_delivery = ExpectedDeliveryOut(
            amount=target.amount,
            unit=target.unit,
            around_the_clock=target.around_the_clock,
            at=await service.expected_delivery_at(session, view.item),
        )
    return out


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
    """A new item (an English name at least), a draft unless `status` is published."""

    async def run() -> Created:
        view = await service.create_item(session, subject, _fields(body), source=source_of(request))
        note.object_id = str(view.item.id)
        out = CatalogItemOut.of(view, staff=True)
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
        values=_fields(body),
        source=source_of(request),
    )
    note.details = {"changed_fields": sorted(body.model_fields_set)}
    set_etag(response, view.item.version)
    return CatalogItemOut.of(view, staff=True)


@router.post(
    "/items/{item_id}/copy",
    summary="Copy a catalog item",
    status_code=status.HTTP_201_CREATED,
    response_model=CatalogItemOut,
)
async def copy_item(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    item_id: uuid.UUID,
    session: TenantSession,
    subject: SignedIn,
    idempotency: Idempotency,
    request: Request,
    note: Annotated[AuditNote, audited("catalog.item_changed", object_type="catalog_item")],
) -> Response:
    """An independent draft, "Copy of …". Send an Idempotency-Key."""

    async def run() -> Created:
        view = await service.copy_item(session, subject, item_id, source=source_of(request))
        note.object_id = str(view.item.id)
        note.details = {"copied_from": str(item_id)}
        out = CatalogItemOut.of(view, staff=True)
        return Created(
            body=out,
            headers={"Location": f"/api/v1/catalog/items/{out.id}", "ETag": f'"{out.version}"'},
        )

    return await idempotency.run({"copy": str(item_id)}, run, status_code=status.HTTP_201_CREATED)


@router.delete(
    "/items/{item_id}",
    summary="Delete a catalog item no request names",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        audited("catalog.item_deleted", object_type="catalog_item", object_param="item_id")
    ],
)
async def delete_item(
    item_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: SignedIn,
    request: Request,
) -> Response:
    """Items with requests are retired instead (409 `catalog_item_in_use`)."""
    await service.delete_item(
        session, subject, item_id, expected_version=version, source=source_of(request)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- settings and the starter catalog -------------------------------------------------------------


@router.get("/settings", summary="The catalog settings")
async def get_settings(
    session: TenantSession, subject: SignedIn, response: Response
) -> CatalogSettingsOut:
    """The tenant's catalog settings (everyone signed in may read them)."""
    del subject
    row = await settings.read(session)
    set_etag(response, row.version)
    return CatalogSettingsOut.of(row)


@router.patch(
    "/settings",
    summary="Change the catalog settings",
    dependencies=[audited("catalog.settings_changed", object_type="catalog_settings")],
)
async def update_settings(
    body: CatalogSettingsIn,
    version: ExpectedVersion,
    session: TenantSession,
    subject: SignedIn,
    response: Response,
) -> CatalogSettingsOut:
    """Change what is sent (catalog_items.manage, If-Match)."""
    row = await settings.update(session, subject, expected_version=version, values=_fields(body))
    set_etag(response, row.version)
    return CatalogSettingsOut.of(row)


@router.get("/starter", summary="Starter items still to publish")
async def starter_status(session: TenantSession, subject: SignedIn) -> CatalogStarterOut:
    """How many starter items are drafts (staff only see the banner; 0 for others)."""
    return CatalogStarterOut(
        drafts=await starter.starter_drafts(session) if is_staff(subject) else 0
    )


@router.post("/starter/publish", summary="Choose a group and publish the starter items")
async def publish_starter(
    body: CatalogStarterPublishIn,
    session: TenantSession,
    subject: SignedIn,
    request: Request,
    note: Annotated[AuditNote, audited("catalog.starter_published", object_type="support_group")],
) -> CatalogStarterPublishOut:
    """The starter drafts get the group; those whose checks pass are published."""
    done = await starter.publish_starter(session, subject, body.group_id, source=source_of(request))
    note.object_id = str(body.group_id)
    note.details = {"published": done.published, "skipped": len(done.skipped)}
    return CatalogStarterPublishOut(published=done.published, skipped=done.skipped)


__all__ = ["router"]
