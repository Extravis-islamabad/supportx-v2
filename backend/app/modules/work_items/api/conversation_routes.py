"""Conversation, followers, typing, counters and reply templates over HTTP (WP-020b). No logic.

Added to each type's router by `build_router`: the collection routes (`/counters`,
`/reply-templates`) before `/{record_id}` so their paths are not read as record IDs, the record
routes after it.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.logging import get_logger
from app.modules.audit import audited
from app.modules.identity_access import PolicyService, Subject, get_policy
from app.modules.work_items.api.people import PersonOut, people_out
from app.modules.work_items.domain.conversation import (
    BODY_MAX,
    RECIPIENTS_MAX,
    TEMPLATE_NAME_MAX,
    DeliveryReason,
    DeliveryState,
    EntryKind,
    FollowReason,
    ReplyMode,
    Visibility,
)
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import (
    WorkItemConversation,
    WorkItemReplyTemplate,
)
from app.modules.work_items.service import conversations as service
from app.modules.work_items.service.realtime import RECORD_KIND, TYPING
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import request_zone
from app.shared.history import source_of
from app.shared.realtime import CENTRIFUGO_STATE, CentrifugoClient, CentrifugoError, Publish
from app.shared.realtime.channels import record

log = get_logger(__name__)

CONFLICT_409: dict[int | str, dict[str, object]] = {
    409: {"description": "version_conflict: someone changed it first."}
}


_people = people_out


class RecipientsOut(BaseModel):
    """Where a reply goes."""

    to: list[str]
    cc: list[str]


class ConversationEntryOut(BaseModel):
    """One reply or note."""

    id: uuid.UUID
    kind: EntryKind
    visibility: Visibility
    reply_mode: ReplyMode | None
    body: str = Field(description="Sanitised rich text (HTML).")
    recipients: RecipientsOut | None
    delivery_state: DeliveryState | None = Field(
        description="Replies only. not_sent: saved, but nothing could send it (see the reason)."
    )
    delivery_reason: DeliveryReason | None
    first_response: bool = Field(description="This entry stamped the first response.")
    mentioned_ids: list[uuid.UUID]
    created_at: datetime
    created_by: uuid.UUID | None
    version: int

    @classmethod
    def of(cls, row: WorkItemConversation) -> "ConversationEntryOut":
        """From the stored row."""
        return cls(
            id=row.id,
            kind=EntryKind(row.kind),
            visibility=Visibility(row.visibility),
            reply_mode=None if row.reply_mode is None else ReplyMode(row.reply_mode),
            body=row.body,
            recipients=None if row.recipients is None else RecipientsOut(**row.recipients),
            delivery_state=None
            if row.delivery_state is None
            else DeliveryState(row.delivery_state),
            delivery_reason=None
            if row.delivery_reason is None
            else DeliveryReason(row.delivery_reason),
            first_response=row.first_response,
            mentioned_ids=list(row.mentioned_ids),
            created_at=row.created_at,
            created_by=row.created_by,
            version=row.version,
        )


class ConversationOut(BaseModel):
    """The conversation, oldest first. The description is the record's own field."""

    items: list[ConversationEntryOut]
    truncated: bool = Field(description="Only the newest entries are listed.")
    people: dict[str, PersonOut] = Field(description="Authors and mentioned people, by user ID.")


class ConversationEntryIn(BaseModel):
    """A reply (to people) or a note (on the record). Notes are private unless you say public."""

    model_config = ConfigDict(extra="forbid")

    kind: EntryKind
    visibility: Visibility | None = Field(
        default=None, description="Notes: private by default. Replies are always public."
    )
    body: str = Field(max_length=BODY_MAX * 2, description="Rich text (HTML), sanitised.")
    reply_mode: ReplyMode | None = Field(default=None, description="Replies: reply by default.")
    to: list[str] = Field(
        default_factory=list,
        max_length=RECIPIENTS_MAX,
        description="Replies: email addresses. Empty: the requester (forward needs one).",
    )
    cc: list[str] = Field(default_factory=list, max_length=RECIPIENTS_MAX)


class ConversationAddedOut(BaseModel):
    """The saved entry, and who was mentioned but not notified (they cannot see the record)."""

    entry: ConversationEntryOut
    not_notified: list[uuid.UUID]
    people: dict[str, PersonOut]
    follow_up: "FollowUpOut | None" = Field(
        default=None,
        description="A requester's reply after the reopen window started this record (098).",
    )


class FollowUpOut(BaseModel):
    """The new record a late reply started; the requester is told its ID."""

    id: uuid.UUID
    display_id: str


class VisibilityIn(BaseModel):
    """Make a note public or private (If-Match: the entry's version)."""

    model_config = ConfigDict(extra="forbid")

    visibility: Visibility


class FollowerOut(BaseModel):
    """Someone following the record."""

    user_id: uuid.UUID
    reason: FollowReason
    grants_access: bool = Field(description="They see the record because they follow it.")
    since: datetime
    removable: bool = Field(description="You may remove them (yourself, assignee, or manager).")


class FollowersOut(BaseModel):
    """Followers, oldest first."""

    items: list[FollowerOut]
    may_manage: bool = Field(description="You may add and remove other people.")
    people: dict[str, PersonOut]


class MentionableOut(BaseModel):
    """A person to mention or add as a follower."""

    id: uuid.UUID
    display_name: str
    email: str
    can_see: bool = Field(description="False: mentioning them notifies nobody (REQ-INC-063).")


class TypingIn(BaseModel):
    """Start or stop showing others that you are writing."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["start", "stop"]
    kind: EntryKind = EntryKind.NOTE


class CounterOut(BaseModel):
    """A personal counter; `counter` is also the view that lists the same records."""

    counter: str
    count: int
    capped: bool


class ReplyTemplateOut(BaseModel):
    """A reply template."""

    id: uuid.UUID
    name: str
    body: str
    version: int

    @classmethod
    def of(cls, row: WorkItemReplyTemplate) -> "ReplyTemplateOut":
        """From the stored row."""
        return cls(id=row.id, name=row.name, body=row.body, version=row.version)


class ReplyTemplateIn(BaseModel):
    """A template's name and text (rich text, sanitised)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=TEMPLATE_NAME_MAX * 2)
    body: str = Field(max_length=BODY_MAX * 2)


def _followers(found: service.Followers, me: uuid.UUID) -> FollowersOut:
    return FollowersOut(
        items=[
            FollowerOut(
                user_id=row.user_id,
                reason=FollowReason(row.reason),
                grants_access=row.grants_access,
                since=row.created_at,
                removable=row.user_id == me or found.may_manage or found.is_assignee,
            )
            for row in found.rows
        ],
        may_manage=found.may_manage,
        people=_people(found.names),
    )


def add_collection_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """`/counters` and `/reply-templates` (before `/{record_id}`)."""
    perm = wtype.permission
    View = Annotated[Subject, Depends(require_permission(perm("view")))]  # noqa: N806 - type alias
    Admin = Annotated[Subject, Depends(require_permission("settings.manage"))]  # noqa: N806 - type alias
    name = wtype.code.replace("_", " ")

    @router.get("/counters", summary="Your personal counters")
    async def counters(session: TenantSession, subject: View, request: Request) -> list[CounterOut]:
        """Overdue, due today, waiting on you, updated by others, unassigned in your groups."""
        found = await service.counters(session, subject, wtype, zone=request_zone(request))
        return [CounterOut(counter=c, count=n, capped=capped) for c, n, capped in found]

    @router.get("/reply-templates", summary="Reply templates")
    async def templates(session: TenantSession, subject: View) -> list[ReplyTemplateOut]:
        """Texts to insert into a reply or note, by name."""
        del subject
        return [ReplyTemplateOut.of(r) for r in await service.templates(session, wtype)]

    @router.post(
        "/reply-templates",
        summary="Add a reply template",
        status_code=status.HTTP_201_CREATED,
        dependencies=[
            audited(f"{name}.reply_template_created", object_type=f"{name}_reply_template")
        ],
    )
    async def create_template(
        body: ReplyTemplateIn, session: TenantSession, subject: Admin, request: Request
    ) -> ReplyTemplateOut:
        """Names are unique (ignoring case)."""
        del subject
        row = await service.create_template(
            session, wtype, name=body.name, body=body.body, source=source_of(request)
        )
        return ReplyTemplateOut.of(row)

    @router.put(
        "/reply-templates/{template_id}",
        summary="Change a reply template",
        responses=CONFLICT_409,
        dependencies=[
            audited(
                f"{name}.reply_template_changed",
                object_type=f"{name}_reply_template",
                object_param="template_id",
            )
        ],
    )
    async def update_template(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        template_id: uuid.UUID,
        body: ReplyTemplateIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Admin,
        request: Request,
        response: Response,
    ) -> ReplyTemplateOut:
        """Needs If-Match."""
        del subject
        row = await service.update_template(
            session,
            wtype,
            template_id,
            expected_version=version,
            name=body.name,
            body=body.body,
            source=source_of(request),
        )
        set_etag(response, row.version)
        return ReplyTemplateOut.of(row)

    @router.delete(
        "/reply-templates/{template_id}",
        summary="Remove a reply template",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=CONFLICT_409,
        dependencies=[
            audited(
                f"{name}.reply_template_deleted",
                object_type=f"{name}_reply_template",
                object_param="template_id",
            )
        ],
    )
    async def delete_template(
        template_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Admin,
        request: Request,
    ) -> Response:
        """Needs If-Match. Text already inserted into replies stays."""
        del subject
        await service.delete_template(
            session, wtype, template_id, expected_version=version, source=source_of(request)
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)


def add_record_routes(router: APIRouter, wtype: WorkItemType) -> None:  # noqa: C901 - one route per operation
    """The conversation, followers, mentions and typing of one record."""
    perm = wtype.permission
    View = Annotated[Subject, Depends(require_permission(perm("view")))]  # noqa: N806 - type alias
    Policy = Annotated[PolicyService, Depends(get_policy)]  # noqa: N806 - type alias
    name = wtype.code.replace("_", " ")

    @router.get("/{record_id}/conversation", summary="Conversation")
    async def conversation(
        record_id: uuid.UUID,
        session: TenantSession,
        subject: View,
        kind: Annotated[EntryKind | None, Query(description="Only replies or only notes.")] = None,
    ) -> ConversationOut:
        """Replies and notes, oldest first; private notes are marked (staff only)."""
        found = await service.timeline(session, subject, wtype, record_id, kind=kind)
        return ConversationOut(
            items=[ConversationEntryOut.of(e) for e in found.entries],
            truncated=found.truncated,
            people=_people(found.names),
        )

    @router.post(
        "/{record_id}/conversation",
        summary="Reply or add a note",
        status_code=status.HTTP_201_CREATED,
        response_model=ConversationAddedOut,
    )
    async def add(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: ConversationEntryIn,
        session: TenantSession,
        subject: View,
        idempotency: Idempotency,
        request: Request,
        policy: Policy,
    ) -> Response:
        """A private note needs add_note; a reply or public note needs reply.

        Replies are saved and marked not_sent until an email channel exists (never dropped).
        Send an Idempotency-Key: a retried request returns the same 201.
        """

        async def run() -> Created:
            added = await service.add_entry(
                session,
                subject,
                wtype,
                record_id,
                kind=body.kind,
                visibility=body.visibility,
                body=body.body,
                reply_mode=body.reply_mode,
                to=body.to,
                cc=body.cc,
                source=source_of(request),
                policy=policy,
            )
            return Created(
                body=ConversationAddedOut(
                    entry=ConversationEntryOut.of(added.entry),
                    not_notified=added.not_notified,
                    people=_people(added.names),
                    follow_up=None
                    if added.follow_up is None
                    else FollowUpOut(id=added.follow_up.id, display_id=added.follow_up.display_id),
                )
            )

        return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)

    @router.patch(
        "/{record_id}/conversation/{entry_id}",
        summary="Make a note public or private",
        responses=CONFLICT_409,
        dependencies=[
            audited(
                f"{name}.note_visibility_changed",
                object_type=name,
                object_param="record_id",
                detail_params=("entry_id",),
            )
        ],
    )
    async def visibility(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        entry_id: uuid.UUID,
        body: VisibilityIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: View,
        request: Request,
        response: Response,
    ) -> ConversationEntryOut:
        """Needs reply and If-Match (the entry's version). Recorded in history and the audit log."""
        row = await service.change_visibility(
            session,
            subject,
            wtype,
            record_id,
            entry_id,
            visibility=body.visibility,
            expected_version=version,
            source=source_of(request),
        )
        set_etag(response, row.version)
        return ConversationEntryOut.of(row)

    @router.get("/{record_id}/followers", summary="Followers")
    async def followers(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> FollowersOut:
        """Who follows the record and why."""
        return _followers(
            await service.list_followers(session, subject, wtype, record_id), subject.user_id
        )

    @router.put("/{record_id}/followers/{user_id}", summary="Follow, or add a follower")
    async def follow(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        user_id: uuid.UUID,
        session: TenantSession,
        subject: View,
        request: Request,
        policy: Policy,
    ) -> FollowersOut:
        """Your own ID: follow it. Someone else: needs manage_followers, and they must see it."""
        found = await service.add_follower(
            session, subject, wtype, record_id, user_id, source=source_of(request), policy=policy
        )
        return _followers(found, subject.user_id)

    @router.delete("/{record_id}/followers/{user_id}", summary="Unfollow, or remove a follower")
    async def unfollow(
        record_id: uuid.UUID,
        user_id: uuid.UUID,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> FollowersOut:
        """Yourself; or anyone, as the assignee or with manage_followers (REQ-INC-151 AC4)."""
        found = await service.remove_follower(
            session, subject, wtype, record_id, user_id, source=source_of(request)
        )
        return _followers(found, subject.user_id)

    @router.get("/{record_id}/mentionable", summary="People to mention or add as followers")
    async def mentionable(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and query options
        record_id: uuid.UUID,
        session: TenantSession,
        subject: View,
        policy: Policy,
        search: Annotated[str | None, Query(max_length=100)] = None,
        limit: Annotated[int, Query(ge=1, le=20)] = 10,
    ) -> list[MentionableOut]:
        """Staff who work on this type, each saying whether they may see this record."""
        found = await service.mentionable(
            session, subject, wtype, record_id, policy, policy, search=search, limit=limit
        )
        return [
            MentionableOut(id=u, display_name=n, email=e, can_see=sees) for u, n, e, sees in found
        ]

    @router.post(
        "/{record_id}/typing",
        summary="Show others you are writing",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def typing(
        record_id: uuid.UUID,
        body: TypingIn,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> Response:
        """A signal on the record channel (REQ-WI-006 AC2); nothing is stored.

        Only staff who may see the record are on that channel (never the requester, AC3).
        """
        await service.check_typing(session, subject, wtype, record_id)
        client: CentrifugoClient | None = getattr(request.app.state, CENTRIFUGO_STATE, None)
        if client is not None:
            channel = record(subject.tenant_id, RECORD_KIND, record_id)
            data = {
                "type": TYPING,
                "ids": [],
                "fields": [body.state, body.kind],
                "by": str(subject.user_id),
            }
            try:
                await client.publish(Publish(channel.name, data))
            except CentrifugoError:
                log.warning("typing_signal_failed", exc_info=True)  # a nicety, never an error
        return Response(status_code=status.HTTP_204_NO_CONTENT)
