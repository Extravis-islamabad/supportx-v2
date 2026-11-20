"""CMDB relationships, maps, business views and versions under /api/v1/cmdb (WP-053 S2).

No business logic here. Reads need `cmdb.view` (scope-filtered in the service, the reader's
current rights). Adding and removing relationships needs `cmdb.edit` (or `cmdb.manage`) on the
source AND every target; relationship types need `cmdb.configure` (audited). Business views are
created with `cmdb.edit` and changed or removed by their owner or `cmdb.configure`. Writes use
If-Match; creates take an Idempotency-Key.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import audited
from app.modules.cmdb.api.routes import RefNameOut, names_out
from app.modules.cmdb.domain import impact as impact_domain
from app.modules.cmdb.domain import relationships as rel
from app.modules.cmdb.domain import types as domain
from app.modules.cmdb.infra.models import BusinessView, Ci, RelationshipTypeRule
from app.modules.cmdb.service import (
    business_views,
    catalogue,
    impact,
    relationships,
    subscribers,
    versions,
)
from app.modules.cmdb.service.relationships import NodeInfo
from app.modules.identity_access import Subject
from app.modules.organization import AudienceKind, count_people, people_in
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, Page, PageResult, list_query
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

Responses = dict[int | str, dict[str, object]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    404: {"model": ProblemDetail, "description": "No such record visible to you."},
}
CONFLICT: Responses = {
    409: {"model": ProblemDetail, "description": "Stale If-Match (version_conflict), or in use."}
}

router = APIRouter(
    prefix="/cmdb",
    tags=["cmdb"],
    dependencies=[Depends(rate_limit("cmdb"))],
    responses=RESPONSES,
)

View = Annotated[Subject, Depends(require_permission(catalogue.VIEW))]
Edit = Annotated[Subject, Depends(require_permission(catalogue.EDIT, catalogue.MANAGE))]
Configure = Annotated[Subject, Depends(require_permission(catalogue.CONFIGURE))]
ViewsQuery = Annotated[ListQuery, Depends(list_query(business_views.VIEW_FIELDS))]
Names = dict[str, str]
IdList = list[uuid.UUID]

# Codes as named schemas (labelled `cmdb_relationship_direction.<code>`, `cmdb_view_layout.<code>`).
RelationshipDirection = rel.RelationshipDirection
ImpactDirection = impact_domain.ImpactDirection
BusinessViewLayout = rel.BusinessViewLayout


def _location(path: str) -> str:
    return f"/api/v1/cmdb/{path}"


# --- schemas: relationship types ------------------------------------------------------------------


class RelationshipRuleIn(BaseModel):
    """CI types the relationship type may join (a rule covers the types below them)."""

    from_ci_type_id: uuid.UUID
    to_ci_type_id: uuid.UUID
    suggested: bool = False


class RelationshipRuleOut(RelationshipRuleIn):
    """One live rule."""

    id: uuid.UUID

    @classmethod
    def of(cls, row: RelationshipTypeRule) -> "RelationshipRuleOut":
        """From the row."""
        return cls(
            id=row.id,
            from_ci_type_id=row.from_ci_type_id,
            to_ci_type_id=row.to_ci_type_id,
            suggested=row.suggested,
        )


class RelationshipTypeIn(BaseModel):
    """A tenant's own relationship type: both names in en, ar and ur."""

    code: str
    names_forward: Names
    names_inverse: Names
    carries_impact: bool = True
    rules: list[RelationshipRuleIn] = Field(default_factory=list, max_length=100)


class RelationshipTypePatch(BaseModel):
    """Fields to change; `rules` replaces every rule. A built-in type keeps its code."""

    names_forward: Names | None = None
    names_inverse: Names | None = None
    carries_impact: bool | None = None
    rules: list[RelationshipRuleIn] | None = Field(default=None, max_length=100)


class RelationshipTypeOut(BaseModel):
    """One relationship type.

    A built-in one is labelled `cmdb_relationship.<code>.forward` and `.inverse`; a tenant's own
    one shows its `names_forward` / `names_inverse`.
    """

    id: uuid.UUID
    code: str
    built_in: bool
    names_forward: Names
    names_inverse: Names
    carries_impact: bool
    rules: list[RelationshipRuleOut]
    relationship_count: int
    suggested: bool
    version: int

    @classmethod
    def of(cls, view: relationships.RelationshipTypeView) -> "RelationshipTypeOut":
        """From the service's view."""
        row = view.record
        return cls(
            id=row.id,
            code=row.code,
            built_in=row.built_in,
            names_forward=row.names_forward,
            names_inverse=row.names_inverse,
            carries_impact=row.carries_impact,
            rules=[RelationshipRuleOut.of(r) for r in view.rules],
            relationship_count=view.relationship_count,
            suggested=view.suggested,
            version=row.version,
        )


class RelationshipTypeList(BaseModel):
    """Relationship types (suggested ones first when asked for one CI type)."""

    items: list[RelationshipTypeOut]


# --- schemas: relationships and the map -----------------------------------------------------------


class RelationshipsIn(BaseModel):
    """Link this CI to up to 50 others with one type: all or nothing.

    `forward`: "this CI <forward name> each target"; `inverse`: "<inverse name>".
    """

    type_id: uuid.UUID
    direction: RelationshipDirection = rel.RelationshipDirection.FORWARD
    targets: IdList = Field(min_length=1, max_length=rel.TARGETS_MAX)


class RelationshipOut(BaseModel):
    """One relationship: from runs on to."""

    id: uuid.UUID
    type_id: uuid.UUID
    from_ci_id: uuid.UUID
    to_ci_id: uuid.UUID
    created_at: datetime
    version: int


class RelationshipsOut(BaseModel):
    """The relationships made."""

    items: list[RelationshipOut]


class OpenCountsOut(BaseModel):
    """Open records on a CI that you may see."""

    incident: int
    problem: int
    change: int


class CiNodeOut(BaseModel):
    """A CI on a map. `restricted`: a CI you may not open; it has a key and nothing else.

    The type shows by `type_label_key` (built-in) or `type_names`; the state by
    `state_label_key` or `state_names`, and its category.
    """

    key: str
    restricted: bool
    depth: int | None = None
    id: uuid.UUID | None = None
    display_id: str | None = None
    name: str | None = None
    type_id: uuid.UUID | None = None
    type_label_key: str | None = None
    type_names: Names = Field(default_factory=dict)
    state_id: uuid.UUID | None = None
    state_category: domain.CiStateCategory | None = None
    state_label_key: str | None = None
    state_names: Names = Field(default_factory=dict)
    version: int | None = None
    counts: OpenCountsOut | None = None

    @classmethod
    def of(cls, key: str, info: NodeInfo, depth: int | None = None) -> "CiNodeOut":
        """From what the reader may know (a placeholder carries its key only)."""
        if not info.visible:
            return cls(key=key, restricted=True, depth=depth)
        return cls(
            key=key,
            restricted=False,
            depth=depth,
            id=info.id,
            display_id=info.display_id,
            name=info.name,
            type_id=info.type_id,
            type_label_key=info.type_label_key,
            type_names=info.type_names,
            state_id=info.state_id,
            state_category=(
                domain.CiStateCategory(info.state_category) if info.state_category else None
            ),
            state_label_key=info.state_label_key,
            state_names=info.state_names,
            version=info.version,
        )


class CiEdgeOut(BaseModel):
    """A link between two node keys (its ID and version only when you may open both ends)."""

    id: uuid.UUID | None
    type_id: uuid.UUID
    from_key: str
    to_key: str
    version: int | None


class CiGraphOut(BaseModel):
    """A CI and its neighbours. `truncated`: more were found than `node_max`; expand a node."""

    nodes: list[CiNodeOut]
    edges: list[CiEdgeOut]
    truncated: bool
    node_max: int
    counts_available: bool


def _graph(graph: relationships.Graph) -> CiGraphOut:
    nodes: list[CiNodeOut] = []
    for node in graph.nodes:
        out = CiNodeOut.of(node.key, node.info, node.depth)
        if node.counts is not None:
            out.counts = OpenCountsOut(
                incident=node.counts.incident,
                problem=node.counts.problem,
                change=node.counts.change,
            )
        nodes.append(out)
    return CiGraphOut(
        nodes=nodes,
        edges=[
            CiEdgeOut(
                id=e.id, type_id=e.type_id, from_key=e.from_key, to_key=e.to_key, version=e.version
            )
            for e in graph.edges
        ],
        truncated=graph.truncated,
        node_max=rel.NODE_MAX,
        counts_available=graph.counts_available,
    )


# --- schemas: impact ------------------------------------------------------------------------------


class ImpactCiOut(CiNodeOut):
    """An affected CI (a `restricted` one has its key, depth and `via` only).

    `via`: the key of the CI it was reached from, so the path back to the start can be drawn.
    """

    via: str | None = None
    via_type_id: uuid.UUID | None = Field(
        default=None, description="The relationship type of the step from `via`."
    )
    via_forward: bool = Field(
        default=True, description="The stored link runs from `via` to this CI (else the reverse)."
    )


class ImpactServiceOut(BaseModel):
    """An affected business service you may see."""

    id: uuid.UUID
    name: str


class AudiencePersonOut(BaseModel):
    """One person a service reaches (for `users.view` holders only)."""

    id: uuid.UUID
    display_name: str


class ImpactOut(BaseModel):
    """What a failure of the CI reaches (`dependents`), or what it relies on (`dependencies`).

    `affected_users`: the active people the subscribers of the affected business services you
    may see reach, each once; `affected_users_partial` when any CI here is restricted (the count
    is "of services you can see"). Null with `affected_users_reason` `not_configured` when none
    of them has subscribers. `affected_people`: up to 50 by name, with `users.view` only.
    `truncated`: the 5,000-CI cap or a read limit cut the walk.
    """

    start: ImpactCiOut
    cis: list[ImpactCiOut]
    services: list[ImpactServiceOut]
    restricted: int = Field(description="How many affected CIs you may not see.")
    affected_users: int | None
    affected_users_partial: bool = False
    affected_users_reason: Literal["not_configured"] | None
    affected_people: list[AudiencePersonOut] | None = None
    truncated: bool
    depth: int
    ci_max: int
    as_of: datetime


def _impact_ci(item: impact.ImpactCi) -> ImpactCiOut:
    node = CiNodeOut.of(item.key, item.info, item.depth)
    return ImpactCiOut(
        **node.model_dump(),
        via=item.via,
        via_type_id=item.via_type_id,
        via_forward=item.via_forward,
    )


# --- schemas: versions ----------------------------------------------------------------------------


class CiVersionItemOut(BaseModel):
    """One saved version."""

    version: int
    saved_at: datetime
    saved_by: uuid.UUID | None
    saved_by_name: str | None


class CiVersionPage(BaseModel):
    """Versions, newest first."""

    items: list[CiVersionItemOut]
    next_cursor: str | None


class CiVersionLinkOut(BaseModel):
    """A relationship as the version holds it, from this CI's side."""

    id: uuid.UUID | None
    type_id: uuid.UUID
    direction: RelationshipDirection
    ci: CiNodeOut


class CiVersionOut(BaseModel):
    """A CI as one version saved it. Values are codes, IDs or text; the UI labels them."""

    version: int
    saved_at: datetime
    saved_by: uuid.UUID | None
    saved_by_name: str | None
    fields: dict[str, Any] = Field(
        description="Built-in fields by name, then custom values as `custom.<key>` (those you "
        "may read now)."
    )
    relationships: list[CiVersionLinkOut]
    masked_fields: list[str] = Field(
        default_factory=list, description="Custom fields this version holds but shows masked."
    )
    names: dict[str, RefNameOut] = Field(
        default_factory=dict,
        description="References in `fields` named for you (site, owner, groups, asset, person "
        "custom values), by the referenced ID; the same map on both sides of a compare.",
    )


class CiAttributeChangeOut(BaseModel):
    """One attribute between two versions."""

    field: str
    kind: Literal["added", "removed", "changed"]
    old: Any = None
    new: Any = None


class CiComparisonOut(BaseModel):
    """Attributes added, removed and changed; relationships added and removed."""

    from_version: CiVersionOut
    to_version: CiVersionOut
    attributes: list[CiAttributeChangeOut]
    relationships_added: list[CiVersionLinkOut]
    relationships_removed: list[CiVersionLinkOut]


def _link(link: versions.LinkView) -> CiVersionLinkOut:
    return CiVersionLinkOut(
        id=link.id,
        type_id=link.type_id,
        direction=link.direction,
        ci=CiNodeOut.of(link.key, link.other),
    )


def _version(view: versions.VersionView) -> CiVersionOut:
    return CiVersionOut(
        version=view.version,
        saved_at=view.saved_at,
        saved_by=view.saved_by,
        saved_by_name=view.saved_by_name,
        fields=view.fields,
        relationships=[_link(link) for link in view.relationships],
        masked_fields=view.masked_fields,
        names=names_out(view.names),
    )


# --- schemas: business views ----------------------------------------------------------------------


class BusinessViewFilters(BaseModel):
    """The map's filters."""

    relationship_type_ids: IdList = Field(default_factory=list, max_length=50)
    ci_type_ids: IdList = Field(default_factory=list, max_length=50)
    show_eol: bool = False
    depth: int = Field(default=1, ge=1, le=rel.DEPTH_MAX)


class NodePosition(BaseModel):
    """A pinned node's place on the canvas."""

    x: float = Field(ge=-rel.COORDINATE_MAX, le=rel.COORDINATE_MAX)
    y: float = Field(ge=-rel.COORDINATE_MAX, le=rel.COORDINATE_MAX)


Positions = Annotated[dict[str, NodePosition], Field(max_length=rel.POSITIONS_MAX)]


class BusinessViewIn(BaseModel):
    """A new business view for one base CI."""

    base_ci_id: uuid.UUID
    name: str = Field(min_length=1, max_length=domain.NAME_MAX)
    description: str | None = Field(default=None, max_length=domain.DESCRIPTION_MAX)
    layout: BusinessViewLayout = rel.BusinessViewLayout.RADIAL
    filters: BusinessViewFilters = Field(default_factory=BusinessViewFilters)
    positions: Positions = Field(default_factory=dict)


class BusinessViewPatch(BaseModel):
    """Fields to change (the base CI stays). Positions of CIs you cannot see are kept."""

    name: str | None = Field(default=None, min_length=1, max_length=domain.NAME_MAX)
    description: str | None = Field(default=None, max_length=domain.DESCRIPTION_MAX)
    layout: BusinessViewLayout | None = None
    filters: BusinessViewFilters | None = None
    positions: Positions | None = None


class BaseCiOut(BaseModel):
    """A view's base CI."""

    id: uuid.UUID
    display_id: str
    name: str

    @classmethod
    def of(cls, base: business_views.BaseCi | None) -> "BaseCiOut | None":
        """From the service's base CI (None stays None)."""
        return None if base is None else cls(id=base.id, display_id=base.display_id, name=base.name)


class BusinessViewListItem(BaseModel):
    """One business view in a list."""

    id: uuid.UUID
    name: str
    description: str | None
    base_ci_id: uuid.UUID
    base_ci: BaseCiOut | None = Field(
        default=None,
        description="The base CI (always one you may see; null only if it was trashed while "
        "this answer was made).",
    )
    layout: BusinessViewLayout
    owner_id: uuid.UUID | None
    updated_at: datetime
    version: int

    @classmethod
    def of(
        cls, row: BusinessView, base: business_views.BaseCi | None = None
    ) -> "BusinessViewListItem":
        """From the row and its base CI."""
        return cls(
            id=row.id,
            name=row.name,
            description=row.description,
            base_ci_id=row.base_ci_id,
            base_ci=BaseCiOut.of(base),
            layout=rel.BusinessViewLayout(row.layout),
            owner_id=row.owner_id,
            updated_at=row.updated_at,
            version=row.version,
        )


class BusinessViewOut(BusinessViewListItem):
    """One business view: its map settings, and only the positions of CIs you may see."""

    filters: BusinessViewFilters
    positions: dict[str, NodePosition]
    owner_name: str | None
    created_at: datetime
    can_edit: bool
    can_delete: bool

    @classmethod
    def of_detail(cls, view: business_views.ViewDetail) -> "BusinessViewOut":
        """From the service's view."""
        row = view.record
        return cls(
            **BusinessViewListItem.of(row, view.base_ci).model_dump(),
            filters=BusinessViewFilters.model_validate(row.filters or {}),
            positions={k: NodePosition.model_validate(v) for k, v in view.positions.items()},
            owner_name=view.owner_name,
            created_at=row.created_at,
            can_edit=view.can_edit,
            can_delete=view.can_delete,
        )


class BusinessViewPage(Page[BusinessViewListItem]):
    """One page of business views."""


def _views_page(
    page: PageResult[BusinessView], bases: dict[uuid.UUID, business_views.BaseCi]
) -> BusinessViewPage:
    return BusinessViewPage(
        items=[BusinessViewListItem.of(r, bases.get(r.base_ci_id)) for r in page.rows],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        estimated_total=page.estimated_total,
    )


def _view_values(body: BaseModel) -> dict[str, Any]:
    values = body.model_dump(include=body.model_fields_set, mode="json")
    values.pop("base_ci_id", None)
    return values


# --- routes: relationship types -------------------------------------------------------------------


@router.get("/relationship-types", summary="Relationship types")
async def list_relationship_types(
    session: TenantSession,
    subject: View,
    for_ci_type: Annotated[
        uuid.UUID | None,
        Query(description="Only the types a CI of this type may take part in, suggested first."),
    ] = None,
) -> RelationshipTypeList:
    """Every relationship type with its rules and how many relationships use it."""
    del subject
    found = await relationships.list_types(session, for_ci_type=for_ci_type)
    return RelationshipTypeList(items=[RelationshipTypeOut.of(v) for v in found])


@router.post(
    "/relationship-types",
    summary="Create a relationship type",
    status_code=status.HTTP_201_CREATED,
    response_model=RelationshipTypeOut,
    dependencies=[audited("cmdb.relationship_type_created", object_type="cmdb_relationship_type")],
)
async def create_relationship_type(
    body: RelationshipTypeIn, session: TenantSession, subject: Configure, idempotency: Idempotency
) -> Response:
    """A tenant's own type. Send an Idempotency-Key: a retried request returns the same 201."""

    async def run() -> Created:
        view = await relationships.create_type(session, subject, body.model_dump(mode="python"))
        out = RelationshipTypeOut.of(view)
        return Created(
            body=out,
            headers={
                "Location": _location(f"relationship-types/{out.id}"),
                "ETag": f'"{out.version}"',
            },
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/relationship-types/{type_id}",
    summary="Change a relationship type",
    responses=CONFLICT,
    dependencies=[audited("cmdb.relationship_type_changed", object_type="cmdb_relationship_type")],
)
async def update_relationship_type(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    type_id: uuid.UUID,
    body: RelationshipTypePatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Configure,
    response: Response,
) -> RelationshipTypeOut:
    """Change the fields you send; `rules` replaces them all. Needs If-Match."""
    view = await relationships.update_type(
        session,
        subject,
        type_id,
        expected_version=version,
        values=body.model_dump(include=body.model_fields_set, mode="python"),
    )
    set_etag(response, view.record.version)
    return RelationshipTypeOut.of(view)


@router.delete(
    "/relationship-types/{type_id}",
    summary="Remove a relationship type",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
    dependencies=[audited("cmdb.relationship_type_deleted", object_type="cmdb_relationship_type")],
)
async def delete_relationship_type(
    type_id: uuid.UUID, version: ExpectedVersion, session: TenantSession, subject: Configure
) -> Response:
    """Refused (409 `cmdb_relationship_type_in_use`, with the count) while links use it."""
    await relationships.delete_type(session, subject, type_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- routes: relationships and the map ------------------------------------------------------------


@router.post(
    "/cis/{ci_id}/relationships",
    summary="Add relationships",
    status_code=status.HTTP_201_CREATED,
    response_model=RelationshipsOut,
    responses=CONFLICT,
)
async def add_relationships(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    ci_id: uuid.UUID,
    body: RelationshipsIn,
    session: TenantSession,
    subject: Edit,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """Link this CI to each target, all or nothing. Send an Idempotency-Key.

    You need edit rights on every CI: 403 `cmdb_relationship_target_denied` names the one you
    cannot change.
    """

    async def run() -> Created:
        made = await relationships.add(
            session,
            subject,
            ci_id,
            type_id=body.type_id,
            direction=body.direction,
            target_ids=body.targets,
            source=source_of(request),
        )
        out = RelationshipsOut(
            items=[
                RelationshipOut(
                    id=r.id,
                    type_id=r.type_id,
                    from_ci_id=r.from_ci_id,
                    to_ci_id=r.to_ci_id,
                    created_at=r.created_at,
                    version=r.version,
                )
                for r in made
            ]
        )
        return Created(body=out, headers={})

    return await idempotency.run(
        {"ci_id": str(ci_id), **body.model_dump(mode="json")},
        run,
        status_code=status.HTTP_201_CREATED,
    )


@router.delete(
    "/relationships/{relationship_id}",
    summary="Remove a relationship",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
)
async def remove_relationship(
    relationship_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Edit,
    request: Request,
) -> Response:
    """Unlink two CIs (both get a new version). You need edit rights on both. Needs If-Match."""
    await relationships.remove(
        session, subject, relationship_id, expected_version=version, source=source_of(request)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _ids(values: IdList | None, name: str) -> IdList:
    ids = list(dict.fromkeys(values or []))
    if len(ids) > rel.TARGETS_MAX:
        raise catalogue.invalid([domain.Problem(name, "too_many")])
    return ids


@router.get("/cis/{ci_id}/neighbours", summary="A CI's relationship map")
async def neighbours(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    ci_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    depth: Annotated[int, Query(ge=1, le=rel.DEPTH_MAX)] = 1,
    types: Annotated[IdList | None, Query(description="Relationship type IDs.")] = None,
    ci_types: Annotated[IdList | None, Query(description="CI type IDs (and below).")] = None,
    eol: Annotated[bool, Query(description="Show end-of-life CIs.")] = False,  # noqa: FBT002 - a query flag (FastAPI)
) -> CiGraphOut:
    """The CI and its neighbours to `depth`, at most 500 nodes.

    A CI you may not open is a `restricted` node with a key only; there are no neighbours to ask
    for from it.
    """
    graph = await relationships.neighbours(
        session,
        subject,
        ci_id,
        depth=depth,
        type_ids=_ids(types, "types"),
        ci_type_ids=_ids(ci_types, "ci_types"),
        show_eol=eol,
    )
    return _graph(graph)


# --- business service subscribers (0185, D-172 (3)) -----------------------------------------------

SubscriberKind = AudienceKind  # labelled `audience_kind.<code>`


class SubscriberIn(BaseModel):
    """One department, site or group the service serves."""

    kind: SubscriberKind
    ref_id: uuid.UUID


class SubscribersIn(BaseModel):
    """The whole list (at most 100): it replaces what is there."""

    subscribers: list[SubscriberIn] = Field(max_length=subscribers.SUBSCRIBERS_MAX)


class SubscriberOut(BaseModel):
    """One subscriber as you may know it: its name, or why not; `removed` if the unit is gone."""

    kind: SubscriberKind
    ref_id: uuid.UUID
    name: RefNameOut
    removed: bool


class SubscribersOut(BaseModel):
    """A business service's subscribers, and how many active people they reach (each once)."""

    business_service: bool = Field(description="Whether this CI takes subscribers at all.")
    items: list[SubscriberOut]
    people: int = Field(description="Active people the live refs reach, each counted once.")


async def _subscribers_out(
    session: TenantSession, ci_id: uuid.UUID, found: list[subscribers.Subscriber]
) -> SubscribersOut:
    record = await session.get(Ci, ci_id)
    is_service = record is not None and record.type_id in await subscribers.service_type_ids(
        session
    )
    return SubscribersOut(
        business_service=is_service,
        items=[
            SubscriberOut(
                kind=s.kind, ref_id=s.ref_id, name=RefNameOut.of(s.name), removed=s.removed
            )
            for s in found
        ],
        people=await count_people(session, await subscribers.audience_of(session, [ci_id])),
    )


@router.get("/cis/{ci_id}/subscribers", summary="A business service's subscribers")
async def get_subscribers(
    ci_id: uuid.UUID, session: TenantSession, subject: View, response: Response
) -> SubscribersOut:
    """The departments, sites and groups the service serves (empty for any other CI)."""
    found = await subscribers.subscribers(session, subject, ci_id)
    record = await session.get(Ci, ci_id)
    if record is not None:
        set_etag(response, record.version)
    return await _subscribers_out(session, ci_id, found)


@router.put(
    "/cis/{ci_id}/subscribers",
    summary="Set a business service's subscribers",
    responses=CONFLICT,
    dependencies=[audited("cmdb.subscribers_changed", object_type="cmdb_ci", object_param="ci_id")],
)
async def put_subscribers(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    ci_id: uuid.UUID,
    body: SubscribersIn,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Edit,
    response: Response,
    request: Request,
) -> SubscribersOut:
    """Replace the list (If-Match on the CI). Only a business service; each unit must exist."""
    found = await subscribers.set_subscribers(
        session,
        subject,
        ci_id,
        [(s.kind, s.ref_id) for s in body.subscribers],
        expected_version=version,
        source=source_of(request),
    )
    record = await session.get(Ci, ci_id)
    if record is not None:
        set_etag(response, record.version)
    return await _subscribers_out(session, ci_id, found)


@router.get("/cis/{ci_id}/subscribers/people", summary="The people a business service reaches")
async def subscriber_people(
    ci_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AudiencePersonOut]:
    """Up to `limit` of them by name; needs `users.view` as well (403 without it)."""
    await subscribers.subscribers(session, subject, ci_id)  # the CI's read check first
    audience = await subscribers.audience_of(session, [ci_id])
    return [
        AudiencePersonOut(id=i, display_name=name)
        for i, name in await people_in(session, subject, audience, limit=limit)
    ]


@router.get("/cis/{ci_id}/impact", summary="What a CI's failure reaches")
async def ci_impact(
    ci_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    direction: ImpactDirection = ImpactDirection.DEPENDENTS,
    depth: Annotated[int, Query(ge=1, le=impact_domain.DEPTH_MAX)] = impact_domain.DEPTH_DEFAULT,
) -> ImpactOut:
    """What a failure of this CI reaches, to `depth`: CIs and business services (or its reliances).

    The walk follows relationship types that carry impact, through CIs you may not see too, so a
    path stays true; those are `restricted` with a key only.
    """
    found = await impact.ci_impact(session, subject, ci_id, direction=direction, depth=depth)
    return ImpactOut(
        start=_impact_ci(found.starts[0]),
        cis=[_impact_ci(c) for c in found.cis],
        services=[ImpactServiceOut(id=s.id, name=s.name) for s in found.services],
        restricted=sum(1 for c in found.cis if c.restricted),
        affected_users=None if found.affected_users is None else found.affected_users.count,
        affected_users_partial=found.affected_users is not None and found.affected_users.partial,
        affected_users_reason="not_configured" if found.affected_users is None else None,
        affected_people=(
            None
            if found.affected_users is None or found.affected_users.people is None
            else [
                AudiencePersonOut(id=i, display_name=name)
                for i, name in found.affected_users.people
            ]
        ),
        truncated=found.truncated,
        depth=depth,
        ci_max=impact_domain.CI_MAX,
        as_of=found.as_of,
    )


# --- routes: versions -----------------------------------------------------------------------------


@router.get("/cis/{ci_id}/versions", summary="Versions of a CI")
async def list_versions(
    ci_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    cursor: Annotated[str | None, Query(description="next_cursor of the previous page.")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> CiVersionPage:
    """Every saved version, newest first."""
    before = int(cursor) if cursor and cursor.isdigit() else None
    items, next_version = await versions.list_versions(
        session, subject, ci_id, before_version=before, limit=limit
    )
    return CiVersionPage(
        items=[
            CiVersionItemOut(
                version=i.version,
                saved_at=i.saved_at,
                saved_by=i.saved_by,
                saved_by_name=i.saved_by_name,
            )
            for i in items
        ],
        next_cursor=None if next_version is None else str(next_version),
    )


@router.get("/cis/{ci_id}/as-of", summary="A CI as of a time")
async def as_of(
    ci_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    at: Annotated[datetime, Query(description="A time with its offset (sent as UTC).")],
) -> CiVersionOut:
    """The CI's fields and relationships as its last version before `at` saved them.

    404 `cmdb_ci_version_not_found` when it did not exist then. Seen through your rights now.
    """
    return _version(await versions.as_of(session, subject, ci_id, at))


@router.get("/cis/{ci_id}/compare", summary="Compare two versions of a CI")
async def compare(
    ci_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    from_version: Annotated[int, Query(alias="from", ge=1)],
    to_version: Annotated[int, Query(alias="to", ge=1)],
) -> CiComparisonOut:
    """Attributes added, removed and changed, and relationships added and removed."""
    result = await versions.compare(
        session, subject, ci_id, from_version=from_version, to_version=to_version
    )
    return CiComparisonOut(
        from_version=_version(result.from_version),
        to_version=_version(result.to_version),
        attributes=[
            CiAttributeChangeOut(field=a.field, kind=a.kind, old=a.old, new=a.new)  # type: ignore[arg-type]  # the domain gives only these kinds
            for a in result.attributes
        ],
        relationships_added=[_link(link) for link in result.added],
        relationships_removed=[_link(link) for link in result.removed],
    )


# --- routes: business views -----------------------------------------------------------------------


@router.get("/business-views", summary="Business views")
async def list_business_views(
    session: TenantSession, query: ViewsQuery, subject: View
) -> BusinessViewPage:
    """Views whose base CI you may see. Filter (`base_ci_id=`, `owner_id=`), sort, page."""
    page = await business_views.list_views(session, subject, query)
    bases = await business_views.base_cis(session, subject, [r.base_ci_id for r in page.rows])
    return _views_page(page, bases)


@router.post(
    "/business-views",
    summary="Create a business view",
    status_code=status.HTTP_201_CREATED,
    response_model=BusinessViewOut,
)
async def create_business_view(
    body: BusinessViewIn,
    session: TenantSession,
    subject: Edit,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """A saved map for a base CI you may see; you own it. Send an Idempotency-Key."""

    async def run() -> Created:
        view = await business_views.create(
            session,
            subject,
            body.base_ci_id,
            body.model_dump(mode="json", exclude={"base_ci_id"}),
            source_of(request),
        )
        out = BusinessViewOut.of_detail(view)
        return Created(
            body=out,
            headers={
                "Location": _location(f"business-views/{out.id}"),
                "ETag": f'"{out.version}"',
            },
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get("/business-views/{view_id}", summary="Get a business view")
async def get_business_view(
    view_id: uuid.UUID, session: TenantSession, subject: View, response: Response
) -> BusinessViewOut:
    """One view (404 `cmdb_business_view_not_found` if you may not see its base CI).

    Read its map with GET …/cis/{base_ci_id}/neighbours and the view's filters.
    """
    view = await business_views.get_view(session, subject, view_id)
    set_etag(response, view.record.version)
    return BusinessViewOut.of_detail(view)


@router.patch("/business-views/{view_id}", summary="Edit a business view", responses=CONFLICT)
async def edit_business_view(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    view_id: uuid.UUID,
    body: BusinessViewPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: View,
    response: Response,
    request: Request,
) -> BusinessViewOut:
    """The owner or `cmdb.configure`: change the fields you send. Needs If-Match."""
    view = await business_views.update(
        session,
        subject,
        view_id,
        expected_version=version,
        values=_view_values(body),
        source=source_of(request),
    )
    set_etag(response, view.record.version)
    return BusinessViewOut.of_detail(view)


@router.post(
    "/business-views/{view_id}/save-as-new",
    summary="Save a business view as a new one",
    status_code=status.HTTP_201_CREATED,
    response_model=BusinessViewOut,
)
async def save_business_view_as_new(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    view_id: uuid.UUID,
    body: BusinessViewPatch,
    session: TenantSession,
    subject: Edit,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """A second view from this one with the changes you send; this one is left as it was.

    You own the new one. Send an Idempotency-Key.
    """

    async def run() -> Created:
        view = await business_views.save_as_new(
            session, subject, view_id, _view_values(body), source_of(request)
        )
        out = BusinessViewOut.of_detail(view)
        return Created(
            body=out,
            headers={
                "Location": _location(f"business-views/{out.id}"),
                "ETag": f'"{out.version}"',
            },
        )

    return await idempotency.run(
        {"save_as_new_of": str(view_id), **body.model_dump(mode="json")},
        run,
        status_code=status.HTTP_201_CREATED,
    )


@router.delete(
    "/business-views/{view_id}",
    summary="Remove a business view",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
)
async def delete_business_view(
    view_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: View,
    request: Request,
) -> Response:
    """The owner or `cmdb.configure` (403 `cmdb_business_view_not_owner` otherwise)."""
    await business_views.remove(
        session, subject, view_id, expected_version=version, source=source_of(request)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
