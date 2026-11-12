"""Life cycle versions over HTTP (ADR-049; WP-046a S4, REQ-INC-049). No logic here.

`/settings/lifecycles/{lifecycle}/...`: the versions of one of the type's transition sets, a
version's moves, and the draft: start it (a copy of the latest published version), replace its
moves (it saves with its problems), publish it, or throw it away; and retire a published version
no longer offered to new records. Each write needs If-Match with the type's settings version
(the life cycle is part of the type's settings), answers with the new one as ETag, and is audited
as a settings change. Who may run a move stays WP-029's transition settings (automation).

Registered before `/{record_id}` so these paths are never read as record IDs.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import PolicyService, Subject, get_policy
from app.modules.work_items.domain.lifecycle import ReasonList, ReasonMode, WorkItemAction
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.domain.versions import VersionState
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import lifecycle_versions as versions
from app.modules.work_items.service.lifecycle_versions import MOVES_MAX, MoveRow
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.history import source_of

FIELDS_MAX = 50


class LifecycleProblemOut(BaseModel):
    """One problem keeping a draft from publishing: a code and the names it concerns."""

    code: str
    params: dict[str, str]


class LifecycleVersionOut(BaseModel):
    """One version of a life cycle."""

    number: int
    state: VersionState
    published_at: datetime | None
    published_by: uuid.UUID | None
    problems: list[LifecycleProblemOut]
    moves: int


class LifecycleVersionsOut(BaseModel):
    """A life cycle's versions, the newest first, and the one new records start on."""

    lifecycle: str
    latest_published: int
    items: list[LifecycleVersionOut]


class LifecycleMoveIO(BaseModel):
    """One move of a version: what it does and, per version, what it needs (ADR-049 §4)."""

    model_config = ConfigDict(extra="forbid")

    from_status: str = Field(max_length=40)
    action: WorkItemAction
    to_status: str | None = Field(
        default=None, max_length=40, description="null: back to the status before (resume)."
    )
    reason_mode: ReasonMode = ReasonMode.NONE
    reason_list: ReasonList | None = None
    permission: str | None = Field(
        default=None, max_length=40, description="An extra right of this type the move needs."
    )
    required_fields: list[str] = Field(default_factory=list, max_length=FIELDS_MAX)


class LifecycleMovesIn(BaseModel):
    """The draft's moves, as a whole."""

    model_config = ConfigDict(extra="forbid")

    moves: list[LifecycleMoveIO] = Field(max_length=MOVES_MAX)


class LifecycleDraftOut(BaseModel):
    """The draft after a save: its number and what still keeps it from publishing."""

    number: int
    problems: list[LifecycleProblemOut]


def _row(move: LifecycleMoveIO) -> MoveRow:
    return MoveRow(
        from_status=move.from_status,
        action=move.action,
        to_status=move.to_status,
        reason_mode=move.reason_mode,
        reason_list=move.reason_list,
        permission=move.permission,
        required_fields=tuple(dict.fromkeys(move.required_fields)),
    )


def _rights(policy: PolicyService) -> frozenset[str]:
    return frozenset(policy.catalogue.permissions)


def add_lifecycle_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """The life cycle version routes of one type."""
    audit = wtype.code.value
    Admin = Annotated[  # noqa: N806 - type alias
        Subject, Depends(require_permission("config.service_desk", "settings.manage"))
    ]
    Settings = Annotated[  # noqa: N806 - type alias
        AuditNote, audited(f"{audit}.settings_changed", object_type=f"{audit}_settings")
    ]
    Policy = Annotated[PolicyService, Depends(get_policy)]  # noqa: N806 - type alias
    base = "/settings/lifecycles/{lifecycle}"

    async def listed(
        session: AsyncSession, lifecycle: str, response: Response
    ) -> LifecycleVersionsOut:
        cat = await config.load(session, wtype)
        set_etag(response, cat.settings_version)
        rows = await versions.list_versions(session, wtype, lifecycle)
        return LifecycleVersionsOut(
            lifecycle=lifecycle,
            latest_published=cat.latest_version(lifecycle),
            items=[
                LifecycleVersionOut(
                    number=v.number,
                    state=v.state,
                    published_at=v.published_at,
                    published_by=v.published_by,
                    problems=[LifecycleProblemOut(**p) for p in v.problems],
                    moves=v.moves,
                )
                for v in rows
            ],
        )

    @router.get(f"{base}/versions", summary="List a life cycle's versions")
    async def list_lifecycle_versions(
        lifecycle: str,
        session: TenantSession,
        subject: Admin,
        response: Response,
    ) -> LifecycleVersionsOut:
        del subject
        return await listed(session, lifecycle, response)

    @router.get(f"{base}/versions/{{number}}/moves", summary="A life cycle version's moves")
    async def list_version_moves(
        lifecycle: str, number: int, session: TenantSession, subject: Admin
    ) -> list[LifecycleMoveIO]:
        del subject
        rows = await versions.moves(session, wtype, lifecycle, number)
        return [
            LifecycleMoveIO(
                from_status=r.from_status,
                action=r.action,
                to_status=r.to_status,
                reason_mode=r.reason_mode,
                reason_list=r.reason_list,
                permission=r.permission,
                required_fields=list(r.required_fields),
            )
            for r in rows
        ]

    @router.post(
        f"{base}/versions",
        summary="Start the next version as a draft (a copy of the latest published one)",
        status_code=status.HTTP_201_CREATED,
    )
    async def start_lifecycle_draft(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        lifecycle: str,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Settings,
        policy: Policy,
    ) -> LifecycleDraftOut:
        number = await versions.start_draft(
            session,
            wtype,
            lifecycle,
            expected_version=version,
            source=source_of(request),
            user_id=subject.user_id,
            allowed_permissions=_rights(policy),
        )
        note.details = {"lifecycle": lifecycle, "draft": number}
        listed_now = await listed(session, lifecycle, response)
        draft = next(v for v in listed_now.items if v.number == number)
        return LifecycleDraftOut(number=number, problems=draft.problems)

    @router.put(f"{base}/draft/moves", summary="Replace the draft's moves")
    async def save_lifecycle_draft(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        lifecycle: str,
        body: LifecycleMovesIn,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Settings,
        policy: Policy,
    ) -> LifecycleDraftOut:
        problems = await versions.save_draft(
            session,
            wtype,
            lifecycle,
            [_row(m) for m in body.moves],
            expected_version=version,
            source=source_of(request),
            user_id=subject.user_id,
            allowed_permissions=_rights(policy),
        )
        listed_now = await listed(session, lifecycle, response)
        number = next(v.number for v in listed_now.items if v.state is VersionState.DRAFT)
        note.details = {"lifecycle": lifecycle, "draft": number, "moves": len(body.moves)}
        return LifecycleDraftOut(
            number=number, problems=[LifecycleProblemOut(**p) for p in problems]
        )

    @router.post(f"{base}/draft/publish", summary="Publish the draft (new records start on it)")
    async def publish_lifecycle_draft(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        lifecycle: str,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Settings,
        policy: Policy,
    ) -> LifecycleVersionsOut:
        number = await versions.publish(
            session,
            wtype,
            lifecycle,
            expected_version=version,
            source=source_of(request),
            user_id=subject.user_id,
            allowed_permissions=_rights(policy),
        )
        note.details = {"lifecycle": lifecycle, "published": number}
        return await listed(session, lifecycle, response)

    @router.delete(
        f"{base}/draft",
        summary="Throw the draft away",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def discard_lifecycle_draft(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        lifecycle: str,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Settings,
    ) -> None:
        await versions.discard_draft(
            session,
            wtype,
            lifecycle,
            expected_version=version,
            source=source_of(request),
            user_id=subject.user_id,
        )
        note.details = {"lifecycle": lifecycle, "draft_discarded": True}
        set_etag(response, (await config.load(session, wtype)).settings_version)

    @router.post(
        f"{base}/versions/{{number}}/retire",
        summary="Stop offering a published version to new records",
    )
    async def retire_lifecycle_version(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        lifecycle: str,
        number: int,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Settings,
    ) -> LifecycleVersionsOut:
        await versions.retire(
            session,
            wtype,
            lifecycle,
            number,
            expected_version=version,
            source=source_of(request),
            user_id=subject.user_id,
        )
        note.details = {"lifecycle": lifecycle, "retired": number}
        return await listed(session, lifecycle, response)


__all__ = ["add_lifecycle_routes"]
