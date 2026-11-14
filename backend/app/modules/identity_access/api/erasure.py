"""GDPR person erasure and legal hold over HTTP (D-171, ADR-052 S1).

- `PUT /people/{user_id}/legal-hold`, `POST /people/{user_id}/legal-hold/lift`:
  `audit.manage_holds`, a recent confirmation, If-Match on the person's version; audited with
  the reason.
- `POST /people/{user_id}/erasure`: admin A asks (`people.erase`, a recent confirmation,
  Idempotency-Key; the person's name typed).
- `POST /erasures/{erasure_id}/approve`: admin B (a different one) approves, with the name typed
  again and a recent confirmation. Refused with `erasure_report_unavailable` while the mentions
  report is missing or incomplete, and `erasure_report_not_reviewed` until it was reviewed.
- `POST /erasures/{erasure_id}/reject`, `GET /erasures`, `GET /erasures/{erasure_id}`.
- The mentions report (S1b, D-171 a): `POST /erasures/{erasure_id}/report/reviewed`,
  `GET /erasures/{erasure_id}/mentions` (places and counts, never text),
  `GET /erasures/{erasure_id}/mentions/{mention_id}/passage` (the current text, when the
  caller's own rights let them read the record; each view audited) and
  `POST /erasures/{erasure_id}/mentions/redact` (the matched words become the marker; each
  mention audited).

Every step is audited (refusals by the error observer). Bodies are validated by the service.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.core.recent_auth import RecentAuth
from app.modules.audit import MANAGE_HOLDS, AuditNote, RequestFacts, audited, record
from app.modules.identity_access.domain import erasure as rules
from app.modules.identity_access.domain.erasure import ErasureReason, ErasureState
from app.modules.identity_access.domain.mentions import MentionMatchKind, MentionState
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.infra.models import PersonErasure, PersonErasureMention, User
from app.modules.identity_access.service import erasure, erasure_mentions, legal_hold
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.clock import system_clock

RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission, or confirm it's you."},
    404: {"model": ProblemDetail, "description": "No such person or erasure."},
    409: {"model": ProblemDetail, "description": "Refused (see the code), or a stale If-Match."},
    422: {"model": ProblemDetail, "description": "Problems by field."},
}
RATE = [Depends(rate_limit("users"))]
Erase = Annotated[Subject, Depends(require_permission("people.erase"))]
Holds = Annotated[Subject, Depends(require_permission(MANAGE_HOLDS))]

people_router = APIRouter(
    prefix="/people", tags=["people-privacy"], dependencies=RATE, responses=RESPONSES
)
erasures_router = APIRouter(
    prefix="/erasures", tags=["people-privacy"], dependencies=RATE, responses=RESPONSES
)


# --- legal hold -----------------------------------------------------------------------------------


class HoldIn(BaseModel):
    """Why the person is held (stored with the hold and in the audit entry; no personal data)."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(description="Required, at most 1000 characters.")


class LiftIn(BaseModel):
    """Why the hold ends (the audit entry's reason)."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1000)


class HoldOut(BaseModel):
    """A person's legal hold; `version` is the person's (send it as If-Match next time)."""

    user_id: uuid.UUID
    held: bool
    held_at: datetime | None
    held_by: uuid.UUID | None
    reason: str | None
    version: int

    @classmethod
    def of(cls, person: User) -> "HoldOut":
        """From the person row."""
        return cls(
            user_id=person.id,
            held=person.legal_hold_at is not None,
            held_at=person.legal_hold_at,
            held_by=person.legal_hold_by,
            reason=person.legal_hold_reason,
            version=person.version,
        )


@people_router.put(
    "/{user_id}/legal-hold",
    summary="Put a person on legal hold",
    dependencies=[RecentAuth],
)
async def set_legal_hold(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    user_id: uuid.UUID,
    body: HoldIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Holds,
    note: Annotated[
        AuditNote, audited("person.legal_hold_set", object_type="user", object_param="user_id")
    ],
) -> HoldOut:
    """A held person cannot be erased. Sending it again changes the reason only."""
    person = await legal_hold.set_hold(
        session,
        subject.user_id,
        user_id,
        body.reason,
        expected_version=version,
        now=system_clock.now(),
    )
    note.reason = person.legal_hold_reason
    set_etag(response, person.version)
    return HoldOut.of(person)


@people_router.post(
    "/{user_id}/legal-hold/lift",
    summary="Lift a person's legal hold",
    dependencies=[RecentAuth],
)
async def lift_legal_hold(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    user_id: uuid.UUID,
    body: LiftIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Holds,
    note: Annotated[
        AuditNote, audited("person.legal_hold_lifted", object_type="user", object_param="user_id")
    ],
) -> HoldOut:
    """409 `legal_hold_not_set` when the person is not held."""
    del subject
    person = await legal_hold.lift_hold(session, user_id, expected_version=version)
    note.reason = body.reason
    set_etag(response, person.version)
    return HoldOut.of(person)


# --- erasure --------------------------------------------------------------------------------------


class ErasureIn(BaseModel):
    """Admin A's request (D-171)."""

    model_config = ConfigDict(extra="forbid")

    reason_code: ErasureReason
    reason_text: str | None = Field(
        default=None, description="At most 1000 characters; never personal data."
    )
    successor_id: uuid.UUID = Field(description="Takes over what the person owns (D4).")
    keep_files: dict[uuid.UUID, str] = Field(
        default_factory=dict,
        description="Uploaded files to keep (D-171 b): file ID → the reason (required).",
    )
    confirm_name: str = Field(description="The person's display name, typed.")


class ApproveIn(BaseModel):
    """Admin B's approval: the person's name typed again."""

    model_config = ConfigDict(extra="forbid")

    confirm_name: str


class RejectIn(BaseModel):
    """Why it is rejected (the audit entry's reason)."""

    model_config = ConfigDict(extra="forbid")

    reason_text: str | None = Field(default=None, max_length=1000)


class ErasureOut(BaseModel):
    """One erasure with its progress. Codes and IDs; the screen labels them."""

    id: uuid.UUID
    person_id: uuid.UUID
    state: ErasureState
    step: int = Field(description="Steps done (0-8); 8 = every step done.")
    steps: int = rules.LAST_STEP
    attempts: int
    reason_code: ErasureReason
    reason_text: str | None
    successor_id: uuid.UUID
    effective_successor_id: uuid.UUID | None
    keep_files: dict[str, str]
    requested_by: uuid.UUID
    requested_at: datetime
    expires_at: datetime
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    rejected_by: uuid.UUID | None
    rejected_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    last_error_code: str | None
    report_ready: bool = Field(description="The mentions report is complete (approval needs it).")
    report: "ReportOut | None" = Field(description="The mentions report; null until built.")
    counts: dict[str, int]
    version: int

    @classmethod
    def of(cls, row: PersonErasure) -> "ErasureOut":
        """From the row."""
        return cls(
            id=row.id,
            person_id=row.person_id,
            state=ErasureState(row.state),
            step=row.step,
            attempts=row.attempts,
            reason_code=ErasureReason(row.reason_code),
            reason_text=row.reason_text,
            successor_id=row.successor_id,
            effective_successor_id=row.effective_successor_id,
            keep_files=dict(row.keep_files),
            requested_by=row.requested_by,
            requested_at=row.requested_at,
            expires_at=row.expires_at,
            approved_by=row.approved_by,
            approved_at=row.approved_at,
            rejected_by=row.rejected_by,
            rejected_at=row.rejected_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            last_error_code=row.last_error_code,
            report_ready=erasure_mentions.report_complete(row.report),
            report=ReportOut.of(row),
            counts={str(k): int(v) for k, v in row.counts.items()},
            version=row.version,
        )


class ReportOut(BaseModel):
    """The mentions report's summary (D-171 a): counts by module and kind, never text."""

    complete: bool = Field(description="Every required module's search ran.")
    building: bool = Field(description="The search is still running.")
    by_module: dict[str, dict[str, int]] = Field(description="Module key → match kind → places.")
    ports_missing: list[str] = Field(description="Required modules not searched yet.")
    attachment_content_searched: bool = Field(
        description="Always false: only file names and details are searched (the screen says so"
        " with `people_erasure.attachment_content_not_searched`)."
    )
    reviewed_at: datetime | None
    reviewed_by: uuid.UUID | None

    @classmethod
    def of(cls, row: PersonErasure) -> "ReportOut | None":
        """From the erasure's row."""
        summary = erasure_mentions.report_summary(row)
        return None if summary is None else cls(**summary)


ErasureOut.model_rebuild()  # ReportOut is defined after it


class ErasuresOut(BaseModel):
    """The tenant's newest erasures (at most 200)."""

    items: list[ErasureOut]


@people_router.post(
    "/{user_id}/erasure",
    summary="Ask for a person's erasure (GDPR)",
    status_code=status.HTTP_201_CREATED,
    response_model=ErasureOut,
    responses={201: {"model": ErasureOut, "description": "Requested (or replayed)."}},
    dependencies=[RecentAuth],
)
async def request_erasure(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    user_id: uuid.UUID,
    body: ErasureIn,
    session: TenantSession,
    subject: Erase,
    idempotency: Idempotency,
    note: Annotated[
        AuditNote,
        audited("person.erasure_requested", object_type="user", object_param="user_id"),
    ],
) -> Response:
    """Another admin must approve within 7 days.

    Refused for yourself, the last tenant admin, a break-glass account, a person on legal hold,
    or when an erasure is already open.
    """
    note.skip = True

    async def operation() -> Created:
        row = await erasure.request_erasure(
            session,
            subject.user_id,
            user_id,
            erasure.ErasureRequest(
                reason_code=body.reason_code,
                reason_text=body.reason_text,
                successor_id=body.successor_id,
                keep_files=body.keep_files,
                confirm_name=body.confirm_name,
            ),
            now=system_clock.now(),
        )
        note.skip = False
        note.reason = row.reason_text
        note.details = {
            "erasure_id": str(row.id),
            "reason_code": row.reason_code,
            "successor_id": str(row.successor_id),
            "files_kept": len(row.keep_files),
        }
        return Created(ErasureOut.of(row), {"ETag": f'"{row.version}"'})

    return await idempotency.run(body, operation)


@erasures_router.get("", summary="Erasures and their progress")
async def list_erasures(
    session: TenantSession,
    subject: Erase,
    state: Annotated[list[ErasureState] | None, Query()] = None,
    person_id: uuid.UUID | None = None,
) -> ErasuresOut:
    """Newest first; filter by state (repeatable) or person."""
    del subject
    rows = await erasure.list_erasures(session, states=state or (), person_id=person_id)
    return ErasuresOut(items=[ErasureOut.of(row) for row in rows])


@erasures_router.get("/{erasure_id}", summary="One erasure")
async def get_erasure(
    erasure_id: uuid.UUID, response: Response, session: TenantSession, subject: Erase
) -> ErasureOut:
    """With its progress (`step` of `steps`) and the code of its last problem."""
    del subject
    row = await erasure.get_erasure(session, erasure_id)
    set_etag(response, row.version)
    return ErasureOut.of(row)


@erasures_router.post(
    "/{erasure_id}/approve",
    summary="Approve an erasure (a second admin)",
    dependencies=[RecentAuth],
)
async def approve_erasure(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    erasure_id: uuid.UUID,
    body: ApproveIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Erase,
    note: Annotated[
        AuditNote,
        audited("person.erasure_approved", object_type="person_erasure", object_param="erasure_id"),
    ],
) -> ErasureOut:
    """Not by the requester. 409 `erasure_report_unavailable` / `erasure_report_not_reviewed`."""
    row = await erasure.approve(
        session,
        subject.user_id,
        erasure_id,
        expected_version=version,
        confirm_name=body.confirm_name,
        now=system_clock.now(),
    )
    note.details = {"person_id": str(row.person_id)}
    set_etag(response, row.version)
    return ErasureOut.of(row)


@erasures_router.post("/{erasure_id}/reject", summary="Reject or withdraw an erasure request")
async def reject_erasure(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    erasure_id: uuid.UUID,
    body: RejectIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Erase,
    note: Annotated[
        AuditNote,
        audited("person.erasure_rejected", object_type="person_erasure", object_param="erasure_id"),
    ],
) -> ErasureOut:
    """Before the job starts only."""
    row = await erasure.reject(
        session, subject.user_id, erasure_id, expected_version=version, now=system_clock.now()
    )
    note.reason = body.reason_text
    note.details = {"person_id": str(row.person_id)}
    set_etag(response, row.version)
    return ErasureOut.of(row)


# --- the mentions report (S1b, D-171 a) ---------------------------------------------------------


class MentionOut(BaseModel):
    """One place the person is named in other people's text. Codes and IDs, never the text."""

    id: uuid.UUID
    module_key: str
    record_type: str
    record_id: uuid.UUID
    field: str
    match_kind: MentionMatchKind
    occurrences: int
    state: MentionState
    redacted_by: uuid.UUID | None
    redacted_at: datetime | None

    @classmethod
    def of(cls, row: PersonErasureMention) -> "MentionOut":
        """From the row."""
        return cls(
            id=row.id,
            module_key=row.module_key,
            record_type=row.record_type,
            record_id=row.record_id,
            field=row.field,
            match_kind=MentionMatchKind(row.match_kind),
            occurrences=row.occurrences,
            state=MentionState(row.state),
            redacted_by=row.redacted_by,
            redacted_at=row.redacted_at,
        )


class MentionsOut(BaseModel):
    """One page of an erasure's mentions, oldest first."""

    items: list[MentionOut]
    next_cursor: str | None
    report: ReportOut | None
    attachment_content_searched: bool = Field(
        default=erasure_mentions.ATTACHMENT_CONTENT_SEARCHED,
        description="Always false: attachment contents are not searched, only file names.",
    )


class PassageOut(BaseModel):
    """The mentioned field's current text (shown to the approver; never stored or logged)."""

    mention_id: uuid.UUID
    text: str


class RedactIn(BaseModel):
    """The mentions to redact (at most 200 per request)."""

    model_config = ConfigDict(extra="forbid")

    mention_ids: list[uuid.UUID] = Field(min_length=1, max_length=erasure_mentions.REDACT_MAX)


class RedactedOut(BaseModel):
    """The erasure after the redaction, and the mentions newly redacted."""

    erasure: ErasureOut
    redacted: list[MentionOut]


def _mention_details(row: PersonErasureMention) -> dict[str, str]:
    return {
        "erasure_id": str(row.erasure_id),
        "module_key": row.module_key,
        "record_type": row.record_type,
        "record_id": str(row.record_id),
        "field": row.field,
        "match_kind": row.match_kind,
    }


@erasures_router.post(
    "/{erasure_id}/report/reviewed",
    summary="Mark an erasure's mentions report reviewed",
    dependencies=[RecentAuth],
)
async def review_report(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    erasure_id: uuid.UUID,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Erase,
    note: Annotated[
        AuditNote,
        audited(
            "person.erasure_report_reviewed",
            object_type="person_erasure",
            object_param="erasure_id",
        ),
    ],
) -> ErasureOut:
    """Approval needs a reviewed report. 409 `erasure_report_unavailable` while it is building."""
    row = await erasure_mentions.mark_reviewed(
        session, subject.user_id, erasure_id, expected_version=version, now=system_clock.now()
    )
    note.details = {"person_id": str(row.person_id)}
    set_etag(response, row.version)
    return ErasureOut.of(row)


@erasures_router.get("/{erasure_id}/mentions", summary="Where the person is named")
async def list_mentions(
    erasure_id: uuid.UUID,
    session: TenantSession,
    subject: Erase,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=erasure_mentions.LIST_LIMIT)] = 50,
) -> MentionsOut:
    """Places in other people's text (module, record, field, kind, count), never the text."""
    del subject
    row, page = await erasure_mentions.list_mentions(
        session, erasure_id, cursor=cursor, limit=limit
    )
    return MentionsOut(
        items=[MentionOut.of(item) for item in page.items],
        next_cursor=page.next_cursor,
        report=ReportOut.of(row),
    )


@erasures_router.get(
    "/{erasure_id}/mentions/{mention_id}/passage", summary="The text a mention is in"
)
async def mention_passage(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    erasure_id: uuid.UUID,
    mention_id: uuid.UUID,
    request: Request,
    response: Response,
    session: TenantSession,
    subject: Erase,
) -> PassageOut:
    """The field's current text, if your own rights let you read that record (else 404).

    Every view is audited (IDs only, never the text).
    """
    row, text = await erasure_mentions.passage(session, subject, erasure_id, mention_id)
    await record(
        session,
        action_code="person.erasure_mention_viewed",
        facts=RequestFacts.of(request),
        object_type="person_erasure",
        object_id=erasure_id,
        details={"mention_id": str(row.id), **_mention_details(row)},
    )
    response.headers["Cache-Control"] = "no-store"
    return PassageOut(mention_id=row.id, text=text)


@erasures_router.post(
    "/{erasure_id}/mentions/redact",
    summary="Redact mentions of the person",
    dependencies=[RecentAuth],
)
async def redact_mentions(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    erasure_id: uuid.UUID,
    body: RedactIn,
    version: ExpectedVersion,
    request: Request,
    response: Response,
    session: TenantSession,
    subject: Erase,
) -> RedactedOut:
    """The matched words become the marker shown as "Removed at the person's request".

    Before the job starts only (requested or approved). 404 `erasure_mention_not_found` when a
    mention belongs to another erasure: nothing is changed then. Each mention is audited.
    """
    done = await erasure_mentions.redact(
        session,
        subject,
        erasure_id,
        body.mention_ids,
        expected_version=version,
        now=system_clock.now(),
    )
    facts = RequestFacts.of(request)
    for mention, changed in done.mentions:
        await record(
            session,
            action_code="person.erasure_mention_redacted",
            facts=facts,
            object_type="person_erasure",
            object_id=erasure_id,
            details={
                "mention_id": str(mention.id),
                "text_changed": changed,
                **_mention_details(mention),
            },
        )
    set_etag(response, done.erasure.version)
    return RedactedOut(
        erasure=ErasureOut.of(done.erasure),
        redacted=[MentionOut.of(mention) for mention, _ in done.mentions],
    )
