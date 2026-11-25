"""Incidents from an outside system's problems: work items' public entry point (WP-053 S7a, D-050).

Lane B's monitoring_integrations calls these three for MonetX (later the generic alert webhook).
Agreed on 2026-11-25 with lane B and the coordinator (plans/wp-053-s7a-entry-point-stub-lane-a.md):

- **In the caller's transaction, as the connection's service account.** The session's own person
  must be `actor` (history and audit name it); its role's rights are checked as for anyone, never
  bypassed. History says source `integration` with the connection in `automation_ref`.
- **One incident per outside problem, for life** (`work_item_external_keys`, 0210). A
  transaction-scoped advisory lock on the key serialises two deliveries of one problem, so the
  second finds the first's key (`exists`) and no orphan incident is ever made; the unique index
  stays as the backstop.
- **Merges are followed when read** along `merged_into` to the live survivor, whose ref is
  returned; a key is never repointed, so an undo needs nothing and the loser never re-creates.
- **Nothing is reopened.** Recovery resolves only an untouched incident (domain rule); else a
  history note and the assignee is told (D-050).
- **Refusals are labelled** (`ExternalProblemRefused`), never a 500.
"""

import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import AppError, PermissionDenied, ValidationFailed
from app.modules import cmdb
from app.modules.identity_access import Subject, active_user_ids, worker_policy
from app.modules.organization import offered_languages
from app.modules.work_items.domain.external_problems import (
    NOTE_CODES,
    Decision,
    ExternalProblemRefused,
    ExternalRecordRef,
    ExternalSource,
    Facts,
    HistoryTouch,
    NoteCode,
    before_update,
    on_recovery,
    plain,
    valid_external_id,
)
from app.modules.work_items.domain.lifecycle import StatusCategory, WorkItemAction
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.types import INCIDENT, Channel
from app.modules.work_items.events import WorkItemSourceRecovered
from app.modules.work_items.infra.models import WorkItem, WorkItemExternalKey, WorkItemLink
from app.modules.work_items.service import ci_links, closing
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.inbound_mail import fit_subject
from app.shared.events.outbox import record_event
from app.shared.history import Change, FieldChange, automated, record_changes
from app.shared.labels import plain_label

KeptOpen = Literal["touched", "not_asked", "closure_rules"]
FIELD = "external_problem"  # the history line's field; its value is a note code, labelled
_FINISHED = frozenset(
    {StatusCategory.RESOLVED.value, StatusCategory.CLOSED.value, StatusCategory.CANCELED.value}
)
_MERGE_HOPS = 10  # a merged survivor merged again: followed, never forever

# The outside system's problem kinds, labelled by the module that owns them (lane B registers
# monitoring_integrations' `problem_kind_label`; work items never imports it, so no cycle).
ProblemKindLabels = Callable[[str, str], str]
_KIND_LABELS: list[ProblemKindLabels] = []


def register_problem_kind_labels(labels: ProblemKindLabels) -> None:
    """The owner's `(code, language) -> label` for the empty-title fallback (one; replaces)."""
    _KIND_LABELS[:] = [labels]


def clear_problem_kind_labels() -> None:
    """Tests only: back to none."""
    _KIND_LABELS.clear()


# --- reading ------------------------------------------------------------------------------------


def _ref(source: ExternalSource) -> dict[str, str]:
    return {"kind": "monitoring", "source": source.kind, "connection_id": str(source.source_id)}


def _own_person(session: AsyncSession, actor: Subject) -> None:
    """History and audit name the session's person: it must be the actor (a programming error)."""
    context = session.info.get(SESSION_TENANT_KEY)
    if context is None or context.user_id != actor.user_id or context.tenant_id != actor.tenant_id:
        msg = "the session must run as the connection's service account (actor)"
        raise ValueError(msg)


async def _lock(session: AsyncSession, source: ExternalSource, external_id: str) -> None:
    """Serialise one problem's deliveries until the transaction ends (tenant in the key)."""
    tenant = session.info[SESSION_TENANT_KEY].tenant_id
    key = f"wiek:{tenant}:{source.kind}:{source.source_id}:{external_id}"
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


async def _key(
    session: AsyncSession, source: ExternalSource, external_id: str
) -> WorkItemExternalKey | None:
    found: WorkItemExternalKey | None = await session.scalar(
        select(WorkItemExternalKey).where(
            WorkItemExternalKey.source_kind == source.kind,
            WorkItemExternalKey.source_id == source.source_id,
            WorkItemExternalKey.external_id == external_id,
        )
    )
    return found


async def _survivor(session: AsyncSession, record_id: uuid.UUID) -> WorkItem | None:
    """The record, or the live record it was merged into (followed through further merges)."""
    current = record_id
    for _ in range(_MERGE_HOPS):
        target = await session.scalar(
            select(WorkItemLink.target_id).where(
                WorkItemLink.source_id == current,
                WorkItemLink.kind == LinkKind.MERGED_INTO.value,
                WorkItemLink.deleted_at.is_(None),
            )
        )
        if target is None:
            break
        current = target
    row: WorkItem | None = await session.scalar(
        select(WorkItem).where(WorkItem.id == current).with_for_update()
    )
    return row


async def _touches(session: AsyncSession, record: WorkItem) -> tuple[HistoryTouch, ...]:
    """The record's history as the touched rule needs it.

    Each row's source, and whether a person made it: an active person of the tenant, never a
    service account. A technician deactivated since counts as no person (said in the PR).
    """
    rows = list(
        await session.execute(
            select(FieldChange.source, FieldChange.actor_type, FieldChange.actor_id).where(
                FieldChange.record_type == items.RECORD_TYPE, FieldChange.record_id == record.id
            )
        )
    )
    ids: set[uuid.UUID] = set()
    for _, actor_type, actor_id in rows:
        if actor_type == "user" and actor_id:
            try:
                ids.add(uuid.UUID(actor_id))
            except ValueError:  # pragma: no cover - a user actor is always a UUID
                continue
    people = await active_user_ids(session, list(ids))
    return tuple(
        HistoryTouch(
            source,
            by_person=actor_type == "user" and actor_id is not None and _is(actor_id, people),
        )
        for source, actor_type, actor_id in rows
    )


def _is(actor_id: str, people: frozenset[uuid.UUID]) -> bool:
    try:
        return uuid.UUID(actor_id) in people
    except ValueError:  # pragma: no cover - see above
        return False


def _out(
    record: WorkItem | None, decision: Decision, *, created: bool = False
) -> ExternalRecordRef:
    if record is None:
        return ExternalRecordRef(None, None, created=False, decision="record_deleted")
    return ExternalRecordRef(record.id, record.display_id, created=created, decision=decision)


async def _facts(session: AsyncSession, key: WorkItemExternalKey) -> tuple[WorkItem | None, Facts]:
    record = await _survivor(session, key.work_item_id)
    deleted = record is None or record.deleted_at is not None
    finished = record is not None and record.status_category in _FINISHED
    return record, Facts(key.last_version, deleted, finished)


# --- writing ------------------------------------------------------------------------------------


async def _note(
    session: AsyncSession, record: WorkItem, code: NoteCode, source: ExternalSource
) -> None:
    """One labelled history line (`external_problem` = the note code), never free text."""
    with automated(session, _ref(source)):
        await record_changes(
            session,
            record_type=items.RECORD_TYPE,
            record_id=record.id,
            version=record.version,
            kind="updated",
            changes=[Change(FIELD, None, code.removeprefix("external_problem."))],
            source="integration",
            subtype=record.type,
        )


async def _subject(  # noqa: PLR0913 - the title and what its fallback is made of
    session: AsyncSession,
    actor: Subject,
    text: str,
    *,
    ci_ids: Sequence[uuid.UUID],
    problem_code: str | None,
    external_id: str,
) -> str:
    """The outside title as plain text, capped (Q3); empty, a labelled one from IDs and codes."""
    title = fit_subject(plain(text))
    if title:
        return title
    _, language = await offered_languages(session)
    refs = await cmdb.ci_refs(session, actor, list(ci_ids[:1])) if ci_ids else {}
    name = next((r.name for r in refs.values() if r.name), None)
    if name and problem_code and _KIND_LABELS:
        kind = _KIND_LABELS[0](problem_code, language)
        return fit_subject(
            plain_label("incidents.external_problem_on_ci", language, ci=name, kind=kind)
        )
    return fit_subject(
        plain_label("incidents.external_problem_subject", language, external_id=external_id)
    )


async def _priority_reason(session: AsyncSession) -> str:
    """The labelled reason a monitoring problem's priority carries, in the tenant's language."""
    _, language = await offered_languages(session)
    return plain_label("incidents.external_problem_priority_reason", language)


async def _requester(
    actor: Subject, session: AsyncSession, requester_id: uuid.UUID | None
) -> uuid.UUID:
    if requester_id is None:
        return actor.user_id  # the service account: requester notices find no address (lane B)
    if requester_id not in await active_user_ids(session, [requester_id]):
        raise ExternalProblemRefused(
            "requester_unusable",  # noqa: EM101 - a refusal code, not a message
            {"requester_id": str(requester_id)},
        )
    return requester_id


def _refusal(error: AppError) -> ExternalProblemRefused:
    """Create's own refusals as the four agreed codes (labelled; the detail stays in params)."""
    fields = {e.field for e in getattr(error, "errors", ()) or ()}
    code = str(getattr(error, "code", "") or "")
    if code == "entitlement_required":  # CIs sent on a plan without the CMDB
        return ExternalProblemRefused("ci_not_linkable", {"code": code})
    if isinstance(error, PermissionDenied) and "ci" in code:
        return ExternalProblemRefused("ci_not_linkable", {"code": code})
    if any("template" in f for f in fields) or "template" in code:
        return ExternalProblemRefused("template_unusable", {"code": code})
    if any("group" in f for f in fields) or "group" in code:
        return ExternalProblemRefused("group_gone", {"code": code})
    if any("priority" in f for f in fields) or "priority" in code:
        return ExternalProblemRefused("priority_unknown", {"code": code})
    if any("ci" in f for f in fields) or "ci" in code:
        return ExternalProblemRefused("ci_not_linkable", {"code": code})
    raise error  # anything else is a real fault the caller must see


async def create_from_external_problem(  # noqa: PLR0913 - the problem, explicit
    session: AsyncSession,
    *,
    actor: Subject,
    source: ExternalSource,
    external_id: str,
    version: int,
    template_id: uuid.UUID,
    priority: str,
    group_id: uuid.UUID | None,
    ci_ids: Sequence[uuid.UUID],
    subject: str,
    opened_at: datetime,
    note_codes: Sequence[NoteCode] = (),
    requester_id: uuid.UUID | None = None,
    problem_code: str | None = None,
) -> ExternalRecordRef:
    """The problem's incident: made once, its CIs linked, as the connection's service account."""
    del opened_at  # the caller's own delay metric; the incident is made now
    if not valid_external_id(external_id):
        msg = "external_id must be 1 to 200 printable characters"
        raise ValueError(msg)
    if any(code not in NOTE_CODES for code in note_codes):
        msg = "note_codes must come from the closed list"
        raise ValueError(msg)
    _own_person(session, actor)
    await _lock(session, source, external_id)
    if (key := await _key(session, source, external_id)) is not None:
        record, facts = await _facts(session, key)
        return _out(None if facts.deleted else record, "exists")
    requester = await _requester(actor, session, requester_id)
    title = await _subject(
        session, actor, subject, ci_ids=ci_ids, problem_code=problem_code, external_id=external_id
    )
    values: dict[str, object] = {
        "subject": title,
        "requester_id": requester,
        "template_id": template_id,
        "priority": priority,
        # A given priority needs its reason (as for anyone): the problem's severity set it.
        "priority_reason": await _priority_reason(session),
        **({"group_id": group_id} if group_id is not None else {}),
    }
    try:
        with automated(session, _ref(source)):
            made = await items.create(
                session,
                actor,
                INCIDENT,
                values,
                source="integration",
                holders=worker_policy(),
                channel=Channel.MONETX if source.kind == "monetx" else Channel.API,
            )
            await ci_links.link_new(session, actor, made.record, list(ci_ids), source="integration")
    except AppError as error:
        raise _refusal(error) from error
    session.add(
        WorkItemExternalKey(
            tenant_id=session.info[SESSION_TENANT_KEY].tenant_id,
            source_kind=source.kind,
            source_id=source.source_id,
            external_id=external_id,
            work_item_id=made.record.id,
            last_version=version,
        )
    )
    for code in note_codes:
        await _note(session, made.record, code, source)
    await session.flush()
    return _out(made.record, "created", created=True)


async def update_from_external_problem(  # noqa: PLR0913 - the problem, explicit
    session: AsyncSession,
    *,
    actor: Subject,
    source: ExternalSource,
    external_id: str,
    version: int,
    priority: str | None = None,
    subject: str | None = None,
) -> ExternalRecordRef | None:
    """A newer version's changes on the open incident; None for a problem never seen."""
    _own_person(session, actor)
    await _lock(session, source, external_id)
    key = await _key(session, source, external_id)
    if key is None:
        return None
    record, facts = await _facts(session, key)
    if (why := before_update(facts, version)) is not None or record is None:
        return _out(None if facts.deleted else record, why or "record_deleted")
    changes: dict[str, object] = {}
    if priority is not None and priority != record.priority:
        changes["priority"] = priority
        changes["priority_reason"] = await _priority_reason(session)
    if subject is not None and (title := fit_subject(plain(subject))) and title != record.subject:
        changes["subject"] = title
    try:
        with automated(session, _ref(source)):
            if changes:
                await items.update(
                    session,
                    actor,
                    INCIDENT,
                    record.id,
                    expected_version=record.version,
                    values=changes,
                    source="integration",
                )
    except (ValidationFailed, PermissionDenied) as error:
        raise _refusal(error) from error
    await _note(session, record, "external_problem.updated", source)
    key.last_version = version
    await session.flush()
    return _out(record, "updated")


async def external_problem_recovered(  # noqa: PLR0913 - the problem, explicit
    session: AsyncSession,
    *,
    actor: Subject,
    source: ExternalSource,
    external_id: str,
    version: int,
    recovered_at: datetime,
    resolve: bool,
) -> ExternalRecordRef | None:
    """D-050: resolve an untouched incident when asked; else a note, and its assignee is told."""
    del recovered_at  # the caller's own record; the move is made now
    _own_person(session, actor)
    await _lock(session, source, external_id)
    key = await _key(session, source, external_id)
    if key is None:
        return None
    record, facts = await _facts(session, key)
    if (why := before_update(facts, version)) is not None or record is None:
        return _out(None if facts.deleted else record, why or "record_deleted")
    key.last_version = version
    decision = on_recovery(
        Facts(
            facts.last_version,
            deleted=False,
            finished=False,
            touches=await _touches(session, record),
        ),
        resolve=resolve,
    )
    if decision == "resolved":
        _, language = await offered_languages(session)
        try:
            with automated(session, _ref(source)):
                await items.transition(
                    session,
                    actor,
                    INCIDENT,
                    record.id,
                    WorkItemAction.RESOLVE,
                    expected_version=record.version,
                    reason_code=None,
                    reason_text=None,
                    source="integration",
                    holders=worker_policy(),
                    closing_input=closing.MoveInput(
                        resolution=plain_label(
                            "incidents.external_problem_recovered_resolution", language
                        )
                    ),
                )
            await _note(session, record, "external_problem.recovered", source)
            await session.flush()
            return _out(record, "resolved")
        except AppError:
            why_open: KeptOpen = "closure_rules"  # the tenant's closure rules keep it open
    else:
        why_open = "not_asked" if not resolve else "touched"
    await _note(session, record, "external_problem.recovered_kept_open", source)
    await record_event(
        session,
        WorkItemSourceRecovered(
            work_item_id=record.id, type=record.type, source_kind=source.kind, why=why_open
        ),
        aggregate_id=record.id,
    )
    await session.flush()
    return _out(record, "noted")


__all__ = [
    "FIELD",
    "ProblemKindLabels",
    "clear_problem_kind_labels",
    "create_from_external_problem",
    "external_problem_recovered",
    "register_problem_kind_labels",
    "update_from_external_problem",
]
