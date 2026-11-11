"""Change advisory boards, the admin API (WP-045b S2; REQ-CHG-040, -041).

`/api/v1/change-boards`: list, read, add (with members, Idempotency-Key), change (If-Match;
`members` replaces them) and remove (not the default board). Reading needs `changes.view` or
the settings permission; changing needs `changes.manage_boards` (the change manager) or the
settings permission, and is audited.
"""

import uuid
from typing import Annotated, Any, Self

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import Subject, user_contacts
from app.modules.work_items.api.people import PersonOut, people_out
from app.modules.work_items.api.settings_routes import CONFLICT
from app.modules.work_items.domain.change_boards import BoardRule
from app.modules.work_items.domain.change_risk import RiskLevel
from app.modules.work_items.domain.types import CHANGE
from app.modules.work_items.service import change_boards as service
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

router = APIRouter(
    prefix="/change-boards",
    tags=["changes"],
    dependencies=[Depends(rate_limit("work_items"))],
)
LOCATION = "/api/v1/change-boards"
View = Annotated[
    Subject,
    Depends(
        require_permission(CHANGE.permission("view"), "config.service_desk", "settings.manage")
    ),
]
# The change manager and administrators only (Haider, 2026-11-10).
Admin = Annotated[Subject, Depends(require_permission("changes.manage_boards", "settings.manage"))]
Note = Annotated[AuditNote, audited("change.board_changed", object_type="change_board")]


class MappingIO(BaseModel):
    """Which changes the board reviews; every list optional (empty: any)."""

    model_config = ConfigDict(extra="forbid")

    change_types: list[str] | None = Field(default=None, max_length=50)
    risk_levels: list[RiskLevel] | None = Field(default=None, max_length=4)
    site_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)
    template_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)


class MemberIO(BaseModel):
    """A person or a group (exactly one)."""

    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    optional: bool | None = None

    @model_validator(mode="after")
    def _one(self) -> Self:
        if (self.user_id is None) == (self.group_id is None):
            msg = "user_id or group_id, exactly one"
            raise ValueError(msg)
        return self


class BoardIn(BaseModel):
    """A new board: a name and at least one member."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=200)
    labels: dict[str, str] | None = Field(default=None, description="{en, ar, ur}")
    description: str | None = Field(default=None, max_length=2000)
    chair_id: uuid.UUID | None = None
    rule: BoardRule | None = None
    mapping: MappingIO | None = None
    position: int | None = Field(default=None, ge=0, le=10_000)
    members: list[MemberIO] = Field(max_length=200)


class BoardPatch(BaseModel):
    """What changes; null clears. `members` replaces the whole list."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    labels: dict[str, str] | None = None
    description: str | None = Field(default=None, max_length=2000)
    chair_id: uuid.UUID | None = None
    rule: BoardRule | None = None
    mapping: MappingIO | None = None
    position: int | None = Field(default=None, ge=0, le=10_000)
    members: list[MemberIO] | None = Field(default=None, max_length=200)


class MemberOut(BaseModel):
    """A member as stored."""

    user_id: uuid.UUID | None
    group_id: uuid.UUID | None
    optional: bool


class BoardOut(BaseModel):
    """A board with its members; `code` is set on the seeded boards only."""

    id: uuid.UUID
    code: str | None
    name: str
    labels: dict[str, str] | None
    description: str | None
    chair_id: uuid.UUID | None
    rule: BoardRule
    mapping: MappingIO | None
    position: int
    is_default: bool
    members: list[MemberOut]
    version: int
    people: dict[str, PersonOut] = Field(
        default_factory=dict, description="The chair and the members who are people, by user ID."
    )

    @classmethod
    def of(cls, board: service.Board, people: dict[str, PersonOut] | None = None) -> Self:
        """From the service's board."""
        row = board.row
        return cls(
            people=people or {},
            id=row.id,
            code=row.code,
            name=row.name,
            labels=row.labels,
            description=row.description,
            chair_id=row.chair_id,
            rule=BoardRule(row.rule),
            mapping=MappingIO.model_validate(row.mapping) if row.mapping else None,
            position=row.position,
            is_default=row.is_default,
            members=[
                MemberOut(user_id=m.user_id, group_id=m.group_id, optional=m.optional)
                for m in board.members
            ],
            version=row.version,
        )


async def _out(session: AsyncSession, boards: list[service.Board]) -> list[BoardOut]:
    """Boards with the names of their people (the board screen names them, never an ID)."""
    ids = {
        str(u)
        for b in boards
        for u in (b.row.chair_id, *(m.user_id for m in b.members))
        if u is not None
    }
    people = people_out(await user_contacts(session, sorted(ids))) if ids else {}
    out = []
    for b in boards:
        own = {str(u) for u in (b.row.chair_id, *(m.user_id for m in b.members)) if u is not None}
        out.append(BoardOut.of(b, {k: v for k, v in people.items() if k in own}))
    return out


def _values(body: BaseModel, *, only_set: bool) -> dict[str, Any]:
    raw = body.model_dump(mode="json", include=body.model_fields_set if only_set else None)
    if raw.get("mapping"):
        raw["mapping"] = {k: v for k, v in raw["mapping"].items() if v is not None}
    return raw


@router.get("", summary="Change advisory boards")
async def list_boards(session: TenantSession, subject: View) -> list[BoardOut]:
    """Every board in order, the two seeded ones included (REQ-CHG-040)."""
    return await _out(session, list(await service.boards(session, subject)))


@router.get("/{board_id}", summary="A change advisory board")
async def get_board(
    board_id: uuid.UUID, session: TenantSession, subject: View, response: Response
) -> BoardOut:
    """One board with its members; ETag is its version."""
    found = await service.board(session, subject, board_id)
    set_etag(response, found.row.version)
    return (await _out(session, [found]))[0]


@router.post(
    "",
    summary="Add a change advisory board",
    status_code=status.HTTP_201_CREATED,
    response_model=BoardOut,
)
async def add_board(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: BoardIn,
    session: TenantSession,
    subject: Admin,
    idempotency: Idempotency,
    request: Request,
    note: Note,
) -> Response:
    """Needs at least one member (REQ-CHG-040 AC1). Send an Idempotency-Key."""

    async def run() -> Created:
        made = await service.create_board(
            session, subject, _values(body, only_set=False), source=source_of(request)
        )
        note.details = {"board": str(made.row.id), "change": "added"}
        out = (await _out(session, [made]))[0]
        return Created(
            body=out,
            headers={"Location": f"{LOCATION}/{out.id}", "ETag": f'"{out.version}"'},
        )

    return await idempotency.run(body.model_dump(mode="json"), run)


@router.patch("/{board_id}", summary="Change a change advisory board", responses=CONFLICT)
async def patch_board(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    board_id: uuid.UUID,
    body: BoardPatch,
    session: TenantSession,
    subject: Admin,
    version: ExpectedVersion,
    response: Response,
    request: Request,
    note: Note,
) -> BoardOut:
    """Needs If-Match. Its members are never all removed."""
    note.details = {"board": str(board_id), "changed_fields": sorted(body.model_fields_set)}
    changed = await service.update_board(
        session,
        subject,
        board_id,
        _values(body, only_set=True),
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, changed.row.version)
    return (await _out(session, [changed]))[0]


@router.delete(
    "/{board_id}",
    summary="Remove a change advisory board",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
)
async def delete_board(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    board_id: uuid.UUID,
    session: TenantSession,
    subject: Admin,
    version: ExpectedVersion,
    request: Request,
    note: Note,
) -> None:
    """Needs If-Match. The default board stays (REQ-CHG-041 AC2)."""
    note.details = {"board": str(board_id), "change": "removed"}
    await service.delete_board(
        session, subject, board_id, expected_version=version, source=source_of(request)
    )
