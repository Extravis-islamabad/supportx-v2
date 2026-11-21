"""CMDB sync rules, their runs and which source wins, under /api/v1/cmdb (WP-053 S4a).

No business logic here. Everything needs `cmdb.configure`; making or changing a rule, its preview
and starting a run also need an unrestricted author (the service checks, lane C's condition 1).
Writes are audited; the order of sources with its before and after (the coordinator's
condition 2). Changes use If-Match; creates take an Idempotency-Key.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.audit import AuditNote, audited
from app.modules.cmdb.api.routes import CONFLICT, RESPONSES
from app.modules.cmdb.domain import sources as source_rules
from app.modules.cmdb.domain import sync as domain
from app.modules.cmdb.domain.sources import AttributeSource
from app.modules.cmdb.infra.models import SyncRule, SyncRun
from app.modules.cmdb.service import catalogue, sync
from app.modules.cmdb.service import sources as sources_service
from app.modules.identity_access import Subject
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.filters import FilterNode
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/cmdb",
    tags=["cmdb"],
    dependencies=[Depends(rate_limit("cmdb"))],
    responses=RESPONSES,
)

Configure = Annotated[Subject, Depends(require_permission(catalogue.CONFIGURE))]
SourceCode = AttributeSource
OutcomeCode = domain.SyncOutcome
TriggerCode = domain.SyncTrigger
StatusCode = domain.SyncRunStatus
KindCode = domain.SyncValueKind


# --- schemas --------------------------------------------------------------------------------------


class SyncRuleIn(BaseModel):
    """A sync rule: which assets, which CI type, and the field map (CI attribute ← asset field)."""

    name: str = Field(min_length=1, max_length=domain.NAME_MAX)
    filter: FilterNode | None = Field(
        default=None,
        description="The assets it takes, in the asset list's DSL over the sync's filter fields "
        "(see …/sync-rules/fields); none: every asset.",
    )
    target_type_id: uuid.UUID
    target_state_id: uuid.UUID | None = None
    field_map: dict[str, str] = Field(
        description="CI attribute (or `custom.<key>`) → syncable asset field; `name` is required.",
        max_length=domain.FIELD_MAP_MAX,
    )
    enabled: bool = False

    def data(self) -> sync.RuleInput:
        """The service's input."""
        return sync.RuleInput(
            name=self.name,
            target_type_id=self.target_type_id,
            target_state_id=self.target_state_id,
            field_map=self.field_map,
            filter=self.filter.model_dump(mode="json", by_alias=True)
            if self.filter is not None
            else None,
            enabled=self.enabled,
        )


class SyncRuleOut(BaseModel):
    """One sync rule."""

    id: uuid.UUID
    name: str
    source_kind: domain.SyncSourceKind
    filter: Any = Field(default=None, description="The stored filter (the DSL's tree).")
    target_type_id: uuid.UUID
    target_state_id: uuid.UUID | None
    field_map: dict[str, str]
    enabled: bool
    updated_at: datetime
    version: int

    @classmethod
    def of(cls, row: SyncRule) -> "SyncRuleOut":
        """From the row."""
        return cls.model_validate(row, from_attributes=True)


class SyncRuleList(BaseModel):
    """Every live sync rule."""

    items: list[SyncRuleOut]


class SyncFieldOut(BaseModel):
    """A field a rule may map: its key and the kind of value it holds."""

    key: str
    kind: KindCode


class SyncFieldsOut(BaseModel):
    """What a rule may map: the syncable asset fields and the CI attributes of a type."""

    asset_fields: list[SyncFieldOut]
    ci_attributes: list[SyncFieldOut] = Field(
        description="The CI's own attributes and, for `type_id`, its plain text custom fields "
        "(`custom.<key>`) that are neither personal nor sensitive."
    )
    filter_fields: list[str] = Field(description="The asset fields a rule's filter may use.")


class SyncPreviewItemOut(BaseModel):
    """What a rule would do with one asset you may see."""

    asset_id: uuid.UUID
    asset_tag: str | None
    asset_name: str | None
    ci_id: uuid.UUID | None
    outcome: OutcomeCode
    changes: list[str]
    kept: list[str]


class SyncPreviewOut(BaseModel):
    """Counts first; `complete` false means only the first assets were counted."""

    total: int
    complete: bool
    counts: dict[str, int]
    items: list[SyncPreviewItemOut]


class SyncRunOut(BaseModel):
    """One run: its trigger, status and counts."""

    id: uuid.UUID
    rule_id: uuid.UUID
    trigger: TriggerCode
    status: StatusCode
    incremental: bool
    started_at: datetime | None
    ended_at: datetime | None
    created_count: int
    updated_count: int
    kept_count: int
    unchanged_count: int
    failed_count: int
    failure: str | None
    created_at: datetime
    version: int

    @classmethod
    def of(cls, row: SyncRun) -> "SyncRunOut":
        """From the row (the item outcomes come with the run on its own)."""
        return cls(
            id=row.id,
            rule_id=row.rule_id,
            trigger=domain.SyncTrigger(row.trigger),
            status=domain.SyncRunStatus(row.status),
            incremental=row.asset_ids is not None,
            started_at=row.started_at,
            ended_at=row.ended_at,
            created_count=row.created_count,
            updated_count=row.updated_count,
            kept_count=row.kept_count,
            unchanged_count=row.unchanged_count,
            failed_count=row.failed_count,
            failure=row.failure,
            created_at=row.created_at,
            version=row.version,
        )


class SyncRunList(BaseModel):
    """A rule's latest runs, newest first."""

    items: list[SyncRunOut]


class SyncRunItemOut(BaseModel):
    """One asset of a run, as you may see it: a CI or asset you may not see is `restricted`."""

    outcome: OutcomeCode
    asset_id: uuid.UUID | None
    asset_label: str | None
    asset_restricted: bool
    ci_id: uuid.UUID | None
    ci_label: str | None
    ci_restricted: bool
    kept: list[str] = Field(description="Attributes a stronger source holds (you may read).")
    code: str | None = Field(description="Why it failed (`errors.field.<code>`).")


class SyncRunDetailOut(SyncRunOut):
    """A run with its item outcomes (at most the first 500 that did something)."""

    items: list[SyncRunItemOut]


class SourcePrecedenceIn(BaseModel):
    """Which source wins: the order for every attribute, and orders of their own."""

    order: list[SourceCode] = Field(description="Strongest first; `hand` leads.")
    overrides: dict[str, list[SourceCode]] = Field(
        default_factory=dict,
        description="An order of its own per attribute (`name`, `custom.<key>` …); `hand` may "
        "rank lower there, so automated sources may overwrite a hand-set value.",
    )


class SourcePrecedenceOut(SourcePrecedenceIn):
    """The order, the attributes an order of their own may be set for, and the version."""

    attributes: list[str]
    version: int


def _precedence_out(
    found: source_rules.Precedence, attributes: list[str], version: int
) -> SourcePrecedenceOut:
    return SourcePrecedenceOut(
        order=list(found.order),
        overrides={k: list(v) for k, v in sorted(found.overrides.items())},
        attributes=attributes,
        version=version,
    )


def _location(path: str) -> str:
    return f"/api/v1/cmdb/{path}"


# --- which source wins (REQ-CMDB-016) -------------------------------------------------------------


@router.get("/settings/source-precedence", summary="Which source wins")
async def get_precedence(
    session: TenantSession, subject: Configure, response: Response
) -> SourcePrecedenceOut:
    """The tenant's order of sources (the CMDB settings' version as the ETag)."""
    del subject
    found, version = await sources_service.precedence(session)
    set_etag(response, version)
    return _precedence_out(found, await sources_service.attributes(session), version)


@router.put(
    "/settings/source-precedence",
    summary="Change which source wins",
    responses=CONFLICT,
)
async def put_precedence(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: SourcePrecedenceIn,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Configure,
    response: Response,
    note: Annotated[
        AuditNote, audited("cmdb.source_precedence_changed", object_type="cmdb_settings")
    ],
) -> SourcePrecedenceOut:
    """Set the order. Needs If-Match (the CMDB settings' version). Audited with before/after."""
    before, after, new_version = await sources_service.change_precedence(
        session, subject, expected_version=version, order=body.order, overrides=body.overrides
    )
    if source_rules.precedence_json(before) == source_rules.precedence_json(after):
        note.skip = True
    note.details = {
        "before": source_rules.precedence_json(before),
        "after": source_rules.precedence_json(after),
    }
    set_etag(response, new_version)
    return _precedence_out(after, await sources_service.attributes(session), new_version)


# --- sync rules (REQ-CMDB-015) --------------------------------------------------------------------


@router.get("/sync-rules", summary="Sync rules")
async def list_rules(session: TenantSession, subject: Configure) -> SyncRuleList:
    """Every live sync rule."""
    return SyncRuleList(items=[SyncRuleOut.of(r) for r in await sync.list_rules(session, subject)])


@router.get("/sync-rules/fields", summary="What a sync rule may map")
async def rule_fields(
    session: TenantSession,
    subject: Configure,
    type_id: Annotated[uuid.UUID | None, Query(description="The target CI type")] = None,
) -> SyncFieldsOut:
    """The syncable asset fields and the CI attributes (with the type's custom text fields)."""
    del subject
    found = await sync.mappable(session, type_id)
    return SyncFieldsOut(
        asset_fields=[SyncFieldOut(key=k, kind=v) for k, v in found.asset_fields.items()],
        ci_attributes=[SyncFieldOut(key=k, kind=v) for k, v in found.ci_attributes.items()],
        filter_fields=list(found.filter_fields),
    )


@router.post("/sync-rules/preview", summary="Preview a sync rule")
async def preview_rule(
    body: SyncRuleIn, session: TenantSession, subject: Configure
) -> SyncPreviewOut:
    """What the rule would do now, as you may see it; nothing is saved or changed."""
    found = await sync.preview(session, subject, body.data())
    return SyncPreviewOut(
        total=found.total,
        complete=found.complete,
        counts=found.counts,
        items=[
            SyncPreviewItemOut(
                asset_id=i.asset_id,
                asset_tag=i.asset_tag,
                asset_name=i.asset_name,
                ci_id=i.ci_id,
                outcome=i.outcome,
                changes=list(i.changes),
                kept=list(i.kept),
            )
            for i in found.items
        ],
    )


@router.post(
    "/sync-rules",
    summary="Create a sync rule",
    status_code=status.HTTP_201_CREATED,
    response_model=SyncRuleOut,
)
async def create_rule(
    body: SyncRuleIn,
    session: TenantSession,
    subject: Configure,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("cmdb.sync_rule_created", object_type="cmdb_sync_rule")],
) -> Response:
    """A new rule. Send an Idempotency-Key: a retried request returns the same 201."""

    async def run() -> Created:
        row = await sync.create_rule(session, subject, body.data())
        note.object_id = str(row.id)
        note.details = {"target_type_id": str(row.target_type_id), "enabled": row.enabled}
        out = SyncRuleOut.of(row)
        return Created(
            body=out,
            headers={"Location": _location(f"sync-rules/{out.id}"), "ETag": f'"{out.version}"'},
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get("/sync-rules/{rule_id}", summary="Get a sync rule")
async def get_rule(
    rule_id: uuid.UUID, session: TenantSession, subject: Configure, response: Response
) -> SyncRuleOut:
    """One live rule (404 `cmdb_sync_rule_not_found` otherwise)."""
    row = await sync.get_rule(session, subject, rule_id)
    set_etag(response, row.version)
    return SyncRuleOut.of(row)


@router.put("/sync-rules/{rule_id}", summary="Change a sync rule", responses=CONFLICT)
async def put_rule(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    rule_id: uuid.UUID,
    body: SyncRuleIn,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Configure,
    response: Response,
    note: Annotated[
        AuditNote,
        audited("cmdb.sync_rule_changed", object_type="cmdb_sync_rule", object_param="rule_id"),
    ],
) -> SyncRuleOut:
    """Replace the rule's settings. Needs If-Match."""
    row, changed = await sync.update_rule(
        session, subject, rule_id, body.data(), expected_version=version
    )
    note.skip = not changed
    note.details = {"changed_fields": changed}
    set_etag(response, row.version)
    return SyncRuleOut.of(row)


@router.delete(
    "/sync-rules/{rule_id}",
    summary="Remove a sync rule",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
    dependencies=[
        audited("cmdb.sync_rule_deleted", object_type="cmdb_sync_rule", object_param="rule_id")
    ],
)
async def delete_rule(
    rule_id: uuid.UUID, version: ExpectedVersion, session: TenantSession, subject: Configure
) -> Response:
    """Remove the rule (its runs stay). Needs If-Match."""
    await sync.delete_rule(session, subject, rule_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- runs -----------------------------------------------------------------------------------------


@router.get("/sync-rules/{rule_id}/runs", summary="A sync rule's runs")
async def list_runs(
    rule_id: uuid.UUID,
    session: TenantSession,
    subject: Configure,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SyncRunList:
    """The latest runs, newest first."""
    runs = await sync.list_runs(session, subject, rule_id, limit=limit)
    return SyncRunList(items=[SyncRunOut.of(r) for r in runs])


@router.post(
    "/sync-rules/{rule_id}/runs",
    summary="Run a sync rule now",
    status_code=status.HTTP_201_CREATED,
    response_model=SyncRunOut,
)
async def start_run(
    rule_id: uuid.UUID,
    session: TenantSession,
    subject: Configure,
    idempotency: Idempotency,
    note: Annotated[
        AuditNote,
        audited("cmdb.sync_run_requested", object_type="cmdb_sync_rule", object_param="rule_id"),
    ],
) -> Response:
    """Queue a full run (one already queued is returned). Send an Idempotency-Key."""

    async def run() -> Created:
        row = await sync.queue_run(session, subject, rule_id)
        note.details = {"run_id": str(row.id)}
        out = SyncRunOut.of(row)
        return Created(body=out, headers={"Location": _location(f"sync-runs/{out.id}")})

    return await idempotency.run(
        {"rule_id": str(rule_id)}, run, status_code=status.HTTP_201_CREATED
    )


@router.get("/sync-runs/{run_id}", summary="A sync run and what it did")
async def get_run(
    run_id: uuid.UUID, session: TenantSession, subject: Configure
) -> SyncRunDetailOut:
    """The run's counts and items; a CI or asset you may not see is `restricted`, with no ID."""
    row, items = await sync.get_run(session, subject, run_id)
    return SyncRunDetailOut(
        **SyncRunOut.of(row).model_dump(),
        items=[
            SyncRunItemOut(
                outcome=domain.SyncOutcome(i.outcome),
                asset_id=i.asset_id,
                asset_label=i.asset_label,
                asset_restricted=i.asset_restricted,
                ci_id=i.ci_id,
                ci_label=i.ci_label,
                ci_restricted=i.ci_restricted,
                kept=list(i.kept),
                code=i.code,
            )
            for i in items
        ],
    )
