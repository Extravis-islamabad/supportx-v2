"""Checklists, the checklist library and personal reminders over HTTP (WP-046a S2).

    GET    /{type}/checklist-library              the enabled library checklists (to add one)
    GET    /{type}/checklist-library/all          every library checklist (admins)
    POST   /{type}/checklist-library              add one (admins)
    PATCH  /{type}/checklist-library/{id}         change, translate or disable one (admins)
    POST   /{type}/checklist-library/import       items read from a CSV (admins; nothing saved)
    GET    /{type}/{record}/checklists            the record's checklists with their items
    POST   /{type}/{record}/checklists            add one, from scratch or a library copy
    POST   /{type}/{record}/checklists/{id}/items add items to one
    PATCH  /{type}/{record}/checklist-items/{id}  tick or untick (If-Match)
    DELETE /{type}/{record}/checklists/{id}       remove one (If-Match)
    GET    /{type}/{record}/reminders             your own reminders on the record
    POST   /{type}/{record}/reminders             set one
    GET    /my-reminders                          your reminders on every record
    PATCH  /my-reminders/{id}                     change, complete or reopen one (If-Match)
    DELETE /my-reminders/{id}                     remove one (If-Match)

No logic here: the services decide.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission, require_signed_in
from app.core.database import TenantSession
from app.modules.audit import audited
from app.modules.identity_access import Subject
from app.modules.work_items.domain.checklists import MAX_FILE_BYTES, TITLE_MAX
from app.modules.work_items.domain.types import WorkItemType, WorkItemTypeCode
from app.modules.work_items.infra.models import (
    ChecklistLibrary,
    WorkItemChecklistItem,
    WorkItemReminder,
)
from app.modules.work_items.service import checklists as service
from app.modules.work_items.service import reminders
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.history import source_of

CONFLICT_409: dict[int | str, dict[str, object]] = {
    409: {"description": "The version is stale; the problem names what changed."}
}


class ChecklistItemOut(BaseModel):
    """One item: who ticked it and when (REQ-INC-077 AC1)."""

    id: uuid.UUID
    text: str
    position: int
    done_at: datetime | None
    done_by: uuid.UUID | None = Field(description="Empty when the system ticked it on close.")
    version: int

    @classmethod
    def of(cls, row: WorkItemChecklistItem) -> "ChecklistItemOut":
        """From a row."""
        return cls.model_validate(row, from_attributes=True)


class ChecklistOut(BaseModel):
    """A checklist with its items and progress."""

    id: uuid.UUID
    title: str
    position: int
    library_id: uuid.UUID | None
    items: list[ChecklistItemOut]
    done: int
    total: int
    version: int

    @classmethod
    def of(cls, view: service.ChecklistView) -> "ChecklistOut":
        """From a view."""
        done = sum(1 for i in view.items if i.done_at is not None)
        return cls(
            id=view.checklist.id,
            title=view.checklist.title,
            position=view.checklist.position,
            library_id=view.checklist.library_id,
            items=[ChecklistItemOut.of(i) for i in view.items],
            done=done,
            total=len(view.items),
            version=view.checklist.version,
        )


class ChecklistIn(BaseModel):
    """A new checklist: a title and items, or a library checklist to copy (AC3)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=TITLE_MAX * 2)
    items: list[str] | None = Field(default=None, max_length=1000)
    library_id: uuid.UUID | None = None


class ChecklistAdded(BaseModel):
    """The new checklist, and how many empty items were left out (AC2)."""

    checklist: ChecklistOut
    dropped: int


class ItemsIn(BaseModel):
    """Items to add at the end (empty ones are left out, AC2)."""

    model_config = ConfigDict(extra="forbid")

    items: list[str] = Field(min_length=1, max_length=1000)


class ItemsAdded(BaseModel):
    """The checklists as they are now, and how many empty items were left out."""

    checklists: list[ChecklistOut]
    dropped: int


class TickIn(BaseModel):
    """Tick (true) or untick (false)."""

    model_config = ConfigDict(extra="forbid")

    done: bool


class LibraryIn(BaseModel):
    """A library checklist: its name, translations and items."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=TITLE_MAX * 2)
    labels: dict[str, str] | None = Field(default=None, description="Names in en, ar, ur.")
    items: list[str] = Field(default_factory=list, max_length=1000)


class LibraryPatch(BaseModel):
    """What to change; `disabled` true stops offering it."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=TITLE_MAX * 2)
    labels: dict[str, str] | None = None
    items: list[str] | None = Field(default=None, max_length=1000)
    disabled: bool | None = None


class LibraryOut(BaseModel):
    """A library checklist."""

    id: uuid.UUID
    name: str
    labels: dict[str, str] | None
    items: list[str]
    disabled: bool
    version: int

    @classmethod
    def of(cls, row: ChecklistLibrary) -> "LibraryOut":
        """From a row."""
        return cls(
            id=row.id,
            name=row.name,
            labels=row.labels,
            items=list(row.items),
            disabled=row.disabled_at is not None,
            version=row.version,
        )


class ChecklistImportRejectedRow(BaseModel):
    """A CSV row that was not imported, and why (REQ-INC-078 AC1)."""

    row: int
    reason: str = Field(description="A code: labels `checklist_import_reason.<code>`.")


class ChecklistImportOut(BaseModel):
    """The items read from the CSV, and the rows refused."""

    items: list[str]
    rejected: list[ChecklistImportRejectedRow]


class ReminderIn(BaseModel):
    """A reminder of your own: a note, when, and how long before to alert you."""

    model_config = ConfigDict(extra="forbid")

    note: str = Field(max_length=1000)
    remind_at: datetime
    alert_minutes: int = Field(default=0, ge=0, le=10080)


class ReminderPatch(BaseModel):
    """What to change; `done` completes (true) or reopens (false) it."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=1000)
    remind_at: datetime | None = None
    alert_minutes: int | None = Field(default=None, ge=0, le=10080)
    done: bool | None = None


class ReminderOut(BaseModel):
    """One of your reminders."""

    id: uuid.UUID
    work_item_id: uuid.UUID
    note: str
    remind_at: datetime
    alert_minutes: int
    alerted_at: datetime | None
    done_at: datetime | None
    version: int

    @classmethod
    def of(cls, row: WorkItemReminder) -> "ReminderOut":
        """From a row."""
        return cls.model_validate(row, from_attributes=True)


class MyReminderOut(ReminderOut):
    """One of your reminders with its record; `available` false once you can no longer see it."""

    record_type: WorkItemTypeCode
    display_id: str | None
    subject: str | None
    available: bool


def add_checklist_collection_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """The library (before `/{record_id}`)."""
    View = Annotated[Subject, Depends(require_permission(wtype.permission("view")))]  # noqa: N806 - type alias
    Admin = Annotated[  # noqa: N806 - type alias
        Subject, Depends(require_permission("config.service_desk", "settings.manage"))
    ]
    audit = wtype.code.value

    @router.get("/checklist-library", summary="Library checklists offered")
    async def offered_library(session: TenantSession, subject: View) -> list[LibraryOut]:
        """The enabled ones, by name."""
        del subject
        rows = await service.library(session, wtype, include_disabled=False)
        return [LibraryOut.of(r) for r in rows]

    @router.get("/checklist-library/all", summary="Every library checklist (admins)")
    async def all_library(session: TenantSession, subject: Admin) -> list[LibraryOut]:
        """Disabled ones too."""
        del subject
        return [
            LibraryOut.of(r) for r in await service.library(session, wtype, include_disabled=True)
        ]

    @router.post(
        "/checklist-library",
        summary="Add a library checklist",
        status_code=status.HTTP_201_CREATED,
        dependencies=[
            audited(f"{audit}.checklist_library_created", object_type=f"{audit}_checklist")
        ],
    )
    async def create_library(body: LibraryIn, session: TenantSession, subject: Admin) -> LibraryOut:
        """A name, translations and items (empty ones left out)."""
        del subject
        return LibraryOut.of(await service.save_library(session, wtype, None, body.model_dump()))

    @router.patch(
        "/checklist-library/{library_id}",
        summary="Change a library checklist",
        responses=CONFLICT_409,
        dependencies=[
            audited(
                f"{audit}.checklist_library_changed",
                object_type=f"{audit}_checklist",
                object_param="library_id",
            )
        ],
    )
    async def update_library(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        library_id: uuid.UUID,
        body: LibraryPatch,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Admin,
        response: Response,
    ) -> LibraryOut:
        """Needs If-Match; records already holding a copy keep theirs (AC3)."""
        del subject
        row = await service.save_library(
            session,
            wtype,
            library_id,
            body.model_dump(include=body.model_fields_set),
            expected_version=version,
        )
        set_etag(response, row.version)
        return LibraryOut.of(row)

    @router.post("/checklist-library/import", summary="Read checklist items from a CSV")
    async def import_library_items(
        request: Request, session: TenantSession, subject: Admin
    ) -> ChecklistImportOut:
        """The raw CSV as the body (up to 5 MB): one item per row, its first column (AC1).

        Good rows are kept and bad ones listed. Saves nothing: the admin reviews the items and
        saves the checklist.
        """
        del subject
        content = bytearray()
        async for piece in request.stream():  # read no more than the limit, as people imports
            content += piece
            if len(content) > MAX_FILE_BYTES:
                break
        found = await service.import_items(session, wtype, bytes(content))
        return ChecklistImportOut(
            items=found.items,
            rejected=[ChecklistImportRejectedRow(row=r, reason=c) for r, c in found.rejected],
        )


def add_checklist_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """A record's checklists and its owner's reminders."""
    View = Annotated[Subject, Depends(require_permission(wtype.permission("view")))]  # noqa: N806 - type alias

    async def _all(
        session: TenantSession, subject: Subject, record_id: uuid.UUID
    ) -> list[ChecklistOut]:
        return [
            ChecklistOut.of(v) for v in await service.checklists(session, subject, wtype, record_id)
        ]

    @router.get("/{record_id}/checklists", summary="Checklists of a record")
    async def list_checklists(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> list[ChecklistOut]:
        """In their order, each with its items and progress."""
        return await _all(session, subject, record_id)

    @router.post(
        "/{record_id}/checklists", summary="Add a checklist", status_code=status.HTTP_201_CREATED
    )
    async def add_checklist(
        record_id: uuid.UUID,
        body: ChecklistIn,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> ChecklistAdded:
        """From scratch or a library copy the record then owns (AC3); empty items said (AC2)."""
        view, dropped = await service.add_checklist(
            session,
            subject,
            wtype,
            record_id,
            body.model_dump(exclude_unset=True, mode="json"),
            source=source_of(request),
        )
        return ChecklistAdded(checklist=ChecklistOut.of(view), dropped=dropped)

    @router.post("/{record_id}/checklists/{checklist_id}/items", summary="Add checklist items")
    async def add_items(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        checklist_id: uuid.UUID,
        body: ItemsIn,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> ItemsAdded:
        """At the end, within the type's limit."""
        dropped = await service.add_items(
            session, subject, wtype, record_id, checklist_id, body.items, source=source_of(request)
        )
        return ItemsAdded(checklists=await _all(session, subject, record_id), dropped=dropped)

    @router.patch(
        "/{record_id}/checklist-items/{item_id}",
        summary="Tick or untick an item",
        responses=CONFLICT_409,
    )
    async def tick(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        item_id: uuid.UUID,
        body: TickIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: View,
        request: Request,
        response: Response,
    ) -> ChecklistItemOut:
        """Needs If-Match; who and when are kept (AC1)."""
        row = await service.tick(
            session,
            subject,
            wtype,
            record_id,
            item_id,
            done=body.done,
            expected_version=version,
            source=source_of(request),
        )
        set_etag(response, row.version)
        return ChecklistItemOut.of(row)

    @router.delete(
        "/{record_id}/checklists/{checklist_id}",
        summary="Remove a checklist",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=CONFLICT_409,
    )
    async def remove_checklist(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        checklist_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> Response:
        """Needs If-Match; its items go with it."""
        await service.remove_checklist(
            session,
            subject,
            wtype,
            record_id,
            checklist_id,
            expected_version=version,
            source=source_of(request),
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/{record_id}/reminders", summary="Your reminders on a record")
    async def record_reminders(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> list[ReminderOut]:
        """Yours only (REQ-INC-082 AC2), open first."""
        rows = await reminders.on_record(session, subject, wtype, record_id)
        return [ReminderOut.of(r) for r in rows]

    @router.post(
        "/{record_id}/reminders", summary="Set a reminder", status_code=status.HTTP_201_CREATED
    )
    async def add_reminder(
        record_id: uuid.UUID,
        body: ReminderIn,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> ReminderOut:
        """Yours; it alerts you at its time minus its lead (AC1)."""
        row = await reminders.create(
            session, subject, wtype, record_id, body.model_dump(), source=source_of(request)
        )
        return ReminderOut.of(row)


my_reminders_router = APIRouter(prefix="/my-reminders", tags=["work_items"])
SignedIn = Annotated[Subject, Depends(require_signed_in())]


@my_reminders_router.get("", summary="Your reminders on every record")
async def my_reminders(
    session: TenantSession, subject: SignedIn, *, open_only: bool = True
) -> list[MyReminderOut]:
    """By time; one on a record you can no longer see reads "no longer available"."""
    return [
        MyReminderOut(
            **ReminderOut.of(v.reminder).model_dump(),
            record_type=WorkItemTypeCode(v.record_type),
            display_id=v.display_id,
            subject=v.subject,
            available=v.display_id is not None,
        )
        for v in await reminders.mine(session, subject, open_only=open_only)
    ]


@my_reminders_router.patch("/{reminder_id}", summary="Change a reminder", responses=CONFLICT_409)
async def update_reminder(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    reminder_id: uuid.UUID,
    body: ReminderPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: SignedIn,
    response: Response,
) -> ReminderOut:
    """Needs If-Match; `done` completes it (AC3) or reopens it."""
    row = await reminders.update(
        session,
        subject,
        reminder_id,
        body.model_dump(include=body.model_fields_set),
        expected_version=version,
    )
    set_etag(response, row.version)
    return ReminderOut.of(row)


@my_reminders_router.delete(
    "/{reminder_id}",
    summary="Remove a reminder",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT_409,
)
async def delete_reminder(
    reminder_id: uuid.UUID, version: ExpectedVersion, session: TenantSession, subject: SignedIn
) -> Response:
    """Needs If-Match."""
    await reminders.delete(session, subject, reminder_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["add_checklist_collection_routes", "add_checklist_routes", "my_reminders_router"]
