"""An asset's financials and notes over HTTP (WP-049b s2). No business logic.

- `/assets/{id}/financials`: totals, depreciation in effect, book value and cost lines
  (REQ-AST-036..038). Needs `assets.view_financials` as well as seeing the asset.
- `/assets/{id}/costs`: cost lines; also `assets.manage`. Creates take an Idempotency-Key,
  changes If-Match.
- `/assets/{id}/notes`: notes (REQ-AST-050) for whoever may see the asset; others' notes are
  changed only with `assets.manage`.

Registered before the record routes (they only match `/assets/{id}` itself, so the order is
for clarity, not need).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.assets.domain.financials import (
    COST_DESCRIPTION_MAX,
    CostKind,
    DepreciationChoice,
    TermsSource,
)
from app.modules.assets.infra.models import AssetCost, AssetNote
from app.modules.assets.service import assets as asset_service
from app.modules.assets.service import financials as service
from app.modules.assets.service import notes
from app.modules.audit import audited
from app.modules.identity_access import Subject, user_names
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

router = APIRouter(
    prefix="/assets",
    tags=["assets"],
    dependencies=[Depends(rate_limit("assets"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing permission or feature."},
    },
)
View = Annotated[Subject, Depends(require_permission(asset_service.VIEW))]
Money = Annotated[Subject, Depends(require_permission(asset_service.VIEW_FINANCIALS))]
NOT_FOUND: dict[int | str, dict[str, object]] = {
    404: {"model": ProblemDetail, "description": "asset_not_found"},
}
WRITE: dict[int | str, dict[str, object]] = {
    404: {"model": ProblemDetail, "description": "asset_not_found, asset_cost_not_found"},
    409: {"model": ProblemDetail, "description": "version_conflict"},
}
Amount = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]


# --- financials ---------------------------------------------------------------------------------


class AssetCostOut(BaseModel):
    """One cost line, in the tenant's base currency."""

    id: uuid.UUID
    asset_id: uuid.UUID
    kind: CostKind
    incurred_on: date
    amount: Decimal
    description: str | None
    created_at: datetime
    created_by: uuid.UUID | None
    version: int

    @classmethod
    def of(cls, row: AssetCost) -> "AssetCostOut":
        """From the row."""
        return cls(
            id=row.id,
            asset_id=row.asset_id,
            kind=CostKind(row.kind),
            incurred_on=row.incurred_on,
            amount=row.amount,
            description=row.description,
            created_at=row.created_at,
            created_by=row.created_by,
            version=row.version,
        )


class DepreciationYearOut(BaseModel):
    """One year of the schedule."""

    year: int
    starts_on: date
    opening: Decimal
    depreciation: Decimal
    closing: Decimal


class DepreciationOut(BaseModel):
    """The depreciation in effect, and where each setting came from (the asset or its product)."""

    method: DepreciationChoice | None = Field(description="None: set nowhere (no depreciation).")
    method_from: TermsSource | None
    useful_life_years: int | None
    life_from: TermsSource | None
    salvage_value: Decimal | None
    salvage_from: TermsSource | None
    starts_on: date | None = Field(description="The asset's acquisition date.")
    own_method: DepreciationChoice | None = Field(description="The asset's own setting.")
    own_useful_life_years: int | None
    own_salvage_value: Decimal | None
    schedule: list[DepreciationYearOut]


class AssetFinancialsOut(BaseModel):
    """The Financials tab (REQ-AST-036..038): the summary cards, depreciation and cost lines."""

    asset_id: uuid.UUID
    asset_version: int
    currency: str = Field(description="The tenant's base currency: every total is in it.")
    purchase_currency: str | None = Field(description="The currency the asset was bought in.")
    currency_differs: bool = Field(
        description="Bought in another currency than the base one: nothing is converted."
    )
    on: date
    purchase: Decimal | None = Field(description="Price plus tax (D-141); None when unknown.")
    operational: Decimal
    disposal: Decimal
    total_cost: Decimal = Field(description="Total cost of ownership.")
    book_value: Decimal | None = Field(description="On `on`; None while no purchase cost is known.")
    cost_centre: str | None
    gl_code: str | None
    depreciation: DepreciationOut
    costs: list[AssetCostOut]


def _choice(code: str | None) -> DepreciationChoice | None:
    return None if code is None else DepreciationChoice(code)


def _financials_out(found: service.AssetFinancials) -> AssetFinancialsOut:
    row, figures, terms = found.asset, found.figures, found.figures.terms
    return AssetFinancialsOut(
        asset_id=row.id,
        asset_version=row.version,
        currency=found.currency,
        purchase_currency=row.currency,
        currency_differs=row.currency is not None and row.currency != found.currency,
        on=figures.on,
        purchase=figures.summary.purchase if figures.purchase_known else None,
        operational=figures.summary.operational,
        disposal=figures.summary.disposal,
        total_cost=figures.summary.total,
        book_value=figures.book_value,
        cost_centre=row.cost_centre,
        gl_code=row.gl_code,
        depreciation=DepreciationOut(
            method=terms.choice,
            method_from=terms.method_from,
            useful_life_years=terms.life_years,
            life_from=terms.life_from,
            salvage_value=terms.salvage,
            salvage_from=terms.salvage_from,
            starts_on=figures.starts_on,
            own_method=(
                None
                if row.depreciation_method is None
                else DepreciationChoice(row.depreciation_method)
            ),
            own_useful_life_years=row.useful_life_years,
            own_salvage_value=row.salvage_value,
            schedule=[
                DepreciationYearOut(
                    year=y.year,
                    starts_on=y.starts_on,
                    opening=y.opening,
                    depreciation=y.depreciation,
                    closing=y.closing,
                )
                for y in figures.schedule
            ],
        ),
        costs=[AssetCostOut.of(line) for line in found.lines],
    )


@router.get("/{asset_id}/financials", summary="An asset's financials", responses=NOT_FOUND)
async def get_financials(
    asset_id: uuid.UUID,
    session: TenantSession,
    subject: Money,
    on: Annotated[date | None, Query(description="Book value on this day (default today).")] = None,
) -> AssetFinancialsOut:
    """Purchase, operational and disposal costs, total cost of ownership, book value, lines."""
    return _financials_out(await service.financials(session, subject, asset_id, on=on))


class AssetCostIn(BaseModel):
    """A new cost line."""

    model_config = ConfigDict(extra="forbid")

    kind: CostKind
    incurred_on: date
    amount: Amount
    description: str | None = Field(default=None, max_length=COST_DESCRIPTION_MAX)


class AssetCostPatch(BaseModel):
    """Cost line fields to change (only those sent)."""

    model_config = ConfigDict(extra="forbid")

    kind: CostKind | None = None
    incurred_on: date | None = None
    amount: Amount | None = None
    description: str | None = Field(default=None, max_length=COST_DESCRIPTION_MAX)


@router.post(
    "/{asset_id}/costs",
    summary="Add a cost line to an asset",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetCostOut,
    responses=NOT_FOUND,
    dependencies=[audited("asset_cost.created", object_type="asset_cost")],
)
async def add_cost(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    asset_id: uuid.UUID,
    body: AssetCostIn,
    session: TenantSession,
    subject: Money,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """A move, service, contract or other cost (base currency). Idempotency-Key.

    The disposal cost is the disposal record's own (`/dispose`), so it counts once.
    """

    async def run() -> Created:
        row = await service.add_cost(
            session, subject, asset_id, body.model_dump(), source=source_of(request)
        )
        return Created(body=AssetCostOut.of(row), headers={"ETag": f'"{row.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


_REQUIRED_COST = {"kind", "incurred_on", "amount"}


@router.patch(
    "/{asset_id}/costs/{cost_id}",
    summary="Change a cost line",
    responses=WRITE,
    dependencies=[audited("asset_cost.updated", object_type="asset_cost", object_param="cost_id")],
)
async def patch_cost(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    asset_id: uuid.UUID,
    cost_id: uuid.UUID,
    body: AssetCostPatch,
    session: TenantSession,
    subject: Money,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AssetCostOut:
    """Change the fields sent (If-Match)."""
    sent = body.model_dump(include=body.model_fields_set)
    values = {k: v for k, v in sent.items() if v is not None or k not in _REQUIRED_COST}
    row = await service.update_cost(
        session, subject, asset_id, cost_id, values,
        expected_version=version, source=source_of(request),
    )  # fmt: skip
    set_etag(response, row.version)
    return AssetCostOut.of(row)


@router.delete(
    "/{asset_id}/costs/{cost_id}",
    summary="Remove a cost line",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
    dependencies=[audited("asset_cost.deleted", object_type="asset_cost", object_param="cost_id")],
)
async def delete_cost(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    asset_id: uuid.UUID,
    cost_id: uuid.UUID,
    session: TenantSession,
    subject: Money,
    version: ExpectedVersion,
    request: Request,
) -> None:
    """Removed (If-Match); its history stays."""
    await service.delete_cost(
        session, subject, asset_id, cost_id, expected_version=version, source=source_of(request)
    )


# --- notes --------------------------------------------------------------------------------------


class AssetNoteOut(BaseModel):
    """A note on an asset; a deleted one keeps who deleted it and when, without its text."""

    id: uuid.UUID
    asset_id: uuid.UUID
    body: str | None = Field(description="Sanitised rich text; None once deleted.")
    author_id: uuid.UUID | None
    author_name: str | None
    mentioned_ids: list[uuid.UUID]
    created_at: datetime
    edited_at: datetime | None = Field(description="Set once edited (the 'edited' marker).")
    deleted_at: datetime | None
    deleted_by_name: str | None
    may_change: bool = Field(description="Whether you may edit or delete it.")
    version: int


class AssetNoteSavedOut(AssetNoteOut):
    """A saved note, and the people mentioned who were not told (they cannot see the asset)."""

    not_notified: list[uuid.UUID] = Field(default_factory=list)


class AssetNoteIn(BaseModel):
    """A note's text (rich text; sanitised on the server)."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=notes.BODY_MAX)


async def _notes_out(
    session: TenantSession, subject: Subject, rows: list[AssetNote]
) -> list[AssetNoteOut]:
    people = {str(p) for r in rows for p in (r.created_by, r.deleted_by) if p is not None}
    names = await user_names(session, sorted(people))
    return [
        AssetNoteOut(
            id=r.id,
            asset_id=r.asset_id,
            body=None if r.deleted_at is not None else r.body,
            author_id=r.created_by,
            author_name=names.get(str(r.created_by)) if r.created_by else None,
            mentioned_ids=list(r.mentioned_ids),
            created_at=r.created_at,
            edited_at=r.edited_at,
            deleted_at=r.deleted_at,
            deleted_by_name=names.get(str(r.deleted_by)) if r.deleted_by else None,
            may_change=r.deleted_at is None and notes.may_change(subject, r),
            version=r.version,
        )
        for r in rows
    ]


async def _saved_out(
    session: TenantSession, subject: Subject, saved: notes.SavedNote
) -> AssetNoteSavedOut:
    (shown,) = await _notes_out(session, subject, [saved.note])
    return AssetNoteSavedOut(**shown.model_dump(), not_notified=saved.not_notified)


@router.get("/{asset_id}/notes", summary="An asset's notes", responses=NOT_FOUND)
async def list_notes(
    asset_id: uuid.UUID, session: TenantSession, subject: View
) -> list[AssetNoteOut]:
    """Newest first; deleted ones as "note deleted" lines."""
    return await _notes_out(session, subject, await notes.list_notes(session, subject, asset_id))


@router.post(
    "/{asset_id}/notes",
    summary="Add a note to an asset",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetNoteSavedOut,
    responses=NOT_FOUND,
    dependencies=[audited("asset_note.created", object_type="asset_note")],
)
async def add_note(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    asset_id: uuid.UUID,
    body: AssetNoteIn,
    session: TenantSession,
    subject: View,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """Mentioned people who may see the asset are told; the others are listed back."""

    async def run() -> Created:
        saved = await notes.add_note(
            session, subject, asset_id, body.body, source=source_of(request)
        )
        out = await _saved_out(session, subject, saved)
        return Created(body=out, headers={"ETag": f'"{saved.note.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


NOTE_WRITE: dict[int | str, dict[str, object]] = {
    403: {"model": ProblemDetail, "description": "Someone else's note, without assets.manage."},
    404: {"model": ProblemDetail, "description": "asset_not_found, asset_note_not_found"},
    409: {"model": ProblemDetail, "description": "version_conflict"},
}


@router.patch(
    "/{asset_id}/notes/{note_id}",
    summary="Edit a note",
    responses=NOTE_WRITE,
    dependencies=[audited("asset_note.updated", object_type="asset_note", object_param="note_id")],
)
async def edit_note(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    asset_id: uuid.UUID,
    note_id: uuid.UUID,
    body: AssetNoteIn,
    session: TenantSession,
    subject: View,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AssetNoteSavedOut:
    """New text (If-Match); the earlier text stays in the note's history."""
    saved = await notes.edit_note(
        session, subject, asset_id, note_id, body.body,
        expected_version=version, source=source_of(request),
    )  # fmt: skip
    set_etag(response, saved.note.version)
    return await _saved_out(session, subject, saved)


@router.delete(
    "/{asset_id}/notes/{note_id}",
    summary="Delete a note",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOTE_WRITE,
    dependencies=[audited("asset_note.deleted", object_type="asset_note", object_param="note_id")],
)
async def delete_note(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    asset_id: uuid.UUID,
    note_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    version: ExpectedVersion,
    request: Request,
) -> None:
    """A "note deleted" line stays with who and when (If-Match)."""
    await notes.delete_note(
        session, subject, asset_id, note_id, expected_version=version, source=source_of(request)
    )


class AssetNoteVersionOut(BaseModel):
    """One save of a note: the text it had after it, who, when."""

    version: int
    kind: str
    actor_name: str | None
    occurred_at: datetime
    body: str | None = Field(description="The text after this save (None: deleted).")
    previous: str | None = Field(description="The text before it.")


@router.get(
    "/{asset_id}/notes/{note_id}/history",
    summary="A note's earlier texts",
    responses={404: {"model": ProblemDetail, "description": "asset_note_not_found"}},
)
async def note_history(
    asset_id: uuid.UUID, note_id: uuid.UUID, session: TenantSession, subject: View
) -> list[AssetNoteVersionOut]:
    """Each save, newest first, with the text before and after (REQ-INC-062 AC1)."""
    entries = await notes.note_history(session, subject, asset_id, note_id)
    names = await user_names(session, [e.actor_id for e in entries if e.actor_id])

    def text(value: Any) -> str | None:  # noqa: ANN401 - a JSON value from history
        return value if isinstance(value, str) else None

    out: list[AssetNoteVersionOut] = []
    for entry in entries:
        body = next((c for c in entry.changes if c.field == "body"), None)
        out.append(
            AssetNoteVersionOut(
                version=entry.version,
                kind=entry.kind,
                actor_name=names.get(entry.actor_id) if entry.actor_id else None,
                occurred_at=entry.occurred_at,
                body=None if body is None else text(body.new),
                previous=None if body is None else text(body.old),
            )
        )
    return out
