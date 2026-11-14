"""Work items' slice of a person's erasure (ADR-052 §4; D-171).

Shaped by lane B's and the coordinator's answers (2026-11-14).

Two ports, so references go before owned rows (the bands):

- `work_items.references` (150): they come off the records that list them. Their follows and
  role holds and board seats go; their addresses come off the people kept informed and off
  other conversations' to/cc (the messages stay); boards and the approval chair they held pass
  to the successor; open tasks they own become unassigned; their pending approvals go to the
  approval administrators (`approver_erased`), never granted.
- `work_items.owned` (550): their private rows go for good (list settings, reminders, timers,
  drafts, private views, personal reply templates); shared views and templates pass to the
  successor; the records they requested or were raised for lose the requester's text (the
  subject becomes the reserved marker, description, custom text and answers are blanked), and
  open ones assigned to them go back to their group's queue. Text written by others stays.

Each call does one bounded batch of one phase (at most `ERASE_BATCH` rows) and returns where to
go on (`phase|after`), so a person with many records never holds a long transaction; a second
full run finds nothing and counts zero. Counts by kind only, never data. Queued bulk jobs need no
step: they run with their creator's rights, which an erased person no longer has.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import Text, cast, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import metadata
from app.modules.identity_access import (
    ERASE_BATCH,
    ErasureBatch,
    register_person_data,
    user_contacts,
)
from app.modules.metadata import FieldType
from app.modules.work_items.domain import approvals as approval_rules
from app.modules.work_items.domain.lifecycle import FINAL_CATEGORIES
from app.modules.work_items.infra.models import (
    ChangeBoard,
    ChangeBoardMember,
    WorkItem,
    WorkItemApprovalSettings,
    WorkItemConversation,
    WorkItemFollower,
    WorkItemListSetting,
    WorkItemReminder,
    WorkItemReplyTemplate,
    WorkItemRoleHolder,
    WorkItemTask,
    WorkItemTimer,
    WorkItemView,
)
from app.modules.work_items.service import drafts, work_items
from app.modules.work_items.service.approvals import reroute_from
from app.shared.erasure import ERASED_ON_REQUEST

# A phase: (name, the batch it runs). A batch takes the cursor's `after` and returns
# (counts, the last id handled or None when the phase is done).
Batch = Callable[["Run", uuid.UUID | None], Awaitable[tuple[dict[str, int], uuid.UUID | None]]]
SHARED = frozenset({"shared", "groups", "everyone"})  # visibilities others use


class Run:
    """One call's inputs, for the phases."""

    def __init__(
        self, session: AsyncSession, person_id: uuid.UUID, successor_id: uuid.UUID
    ) -> None:
        self.session = session
        self.person_id = person_id
        self.successor_id = successor_id


async def _batched(
    phases: Sequence[tuple[str, Batch]], run: Run, cursor: str | None
) -> ErasureBatch:
    """Run the current phase's next batch; a phase with nothing to do hands on at once.

    So a person with nothing left is done in one call (cursor None, zero counts: the contract's
    idempotence), and a call that did work says where to go on (`phase|after`).
    """
    names = [name for name, _ in phases]
    phase, _, after_text = (cursor or f"{names[0]}|").partition("|")
    after = uuid.UUID(after_text) if after_text else None
    for index in range(names.index(phase), len(names)):
        counts, last = await phases[index][1](run, after)
        if last is not None:  # a full batch: more of this phase may follow
            return ErasureBatch(counts, f"{names[index]}|{last}")
        if counts:  # this phase is done; the next starts with the next call
            following = names[index + 1] if index + 1 < len(names) else None
            return ErasureBatch(counts, None if following is None else f"{following}|")
        after = None  # nothing here: on to the next phase in this call
    return ErasureBatch({})


def _deleting(kind: str, model: Any, owner: Any) -> Batch:  # noqa: ANN401 - a model and its column
    async def batch(run: Run, after: uuid.UUID | None) -> tuple[dict[str, int], uuid.UUID | None]:
        query = select(model.id).where(owner == run.person_id).order_by(model.id).limit(ERASE_BATCH)
        if after is not None:
            query = query.where(model.id > after)
        ids = list((await run.session.scalars(query)).all())
        if ids:
            await run.session.execute(delete(model).where(model.id.in_(ids)))
        done = len(ids) < ERASE_BATCH
        return ({kind: len(ids)} if ids else {}), (None if done else ids[-1])

    return batch


# --- references (150) -----------------------------------------------------------------------------


async def _follows(run: Run, after: uuid.UUID | None) -> tuple[dict[str, int], uuid.UUID | None]:
    """Their follows: composite key (record, person), so all at once (a person follows few)."""
    del after
    result = await run.session.execute(
        delete(WorkItemFollower).where(WorkItemFollower.user_id == run.person_id)
    )
    count = int(getattr(result, "rowcount", 0) or 0)
    return ({"followers_removed": count} if count else {}), None


async def _role_holds(run: Run, after: uuid.UUID | None) -> tuple[dict[str, int], uuid.UUID | None]:
    del after
    held = await run.session.execute(
        delete(WorkItemRoleHolder).where(WorkItemRoleHolder.user_id == run.person_id)
    )
    seats = await run.session.execute(
        delete(ChangeBoardMember).where(ChangeBoardMember.user_id == run.person_id)
    )
    counts = {
        "role_holds_removed": int(getattr(held, "rowcount", 0) or 0),
        "board_seats_removed": int(getattr(seats, "rowcount", 0) or 0),
    }
    return {k: v for k, v in counts.items() if v}, None


async def _chairs(run: Run, after: uuid.UUID | None) -> tuple[dict[str, int], uuid.UUID | None]:
    """Boards they chair and the approval chair: the successor holds them now."""
    del after
    moved = 0
    for board in await run.session.scalars(
        select(ChangeBoard).where(ChangeBoard.chair_id == run.person_id).with_for_update()
    ):
        board.chair_id = run.successor_id
        board.version += 1
        moved += 1
    for settings in await run.session.scalars(
        select(WorkItemApprovalSettings)
        .where(WorkItemApprovalSettings.chair_user_id == run.person_id)
        .with_for_update()
    ):
        settings.chair_user_id = run.successor_id
        moved += 1
    await run.session.flush()
    return ({"chairs_handed_over": moved} if moved else {}), None


async def _tasks(run: Run, after: uuid.UUID | None) -> tuple[dict[str, int], uuid.UUID | None]:
    """Open tasks they own become unassigned (done ones keep their name)."""
    query = (
        select(WorkItemTask)
        .where(WorkItemTask.owner_id == run.person_id, WorkItemTask.status == "open")
        .order_by(WorkItemTask.id)
        .limit(ERASE_BATCH)
        .with_for_update()
    )
    if after is not None:
        query = query.where(WorkItemTask.id > after)
    rows = list((await run.session.scalars(query)).all())
    for task in rows:
        task.owner_id = None
        task.version += 1
    await run.session.flush()
    last = rows[-1].id if len(rows) == ERASE_BATCH else None
    return ({"tasks_unassigned": len(rows)} if rows else {}), last


async def _approvals(run: Run, after: uuid.UUID | None) -> tuple[dict[str, int], uuid.UUID | None]:
    """Pending approvals they hold go to the approval administrators: never granted."""
    del after
    moved = await reroute_from(
        run.session, run.person_id, reason=approval_rules.RouteReason.APPROVER_ERASED
    )
    return ({"approvals_rerouted": moved} if moved else {}), None


async def _addresses(run: Run) -> set[str]:
    key = str(run.person_id)
    contact = (await user_contacts(run.session, [key])).get(key)
    email = contact[1] if contact else None
    return {email.casefold()} if email else set()


async def _kept_informed(
    run: Run, after: uuid.UUID | None
) -> tuple[dict[str, int], uuid.UUID | None]:
    """Their address off the people kept informed of records (REQ-INC-066)."""
    addresses = await _addresses(run)
    if not addresses:
        return {}, None
    query = (
        select(WorkItem)
        .where(WorkItem.notify_emails.overlap(sorted(addresses)))
        .order_by(WorkItem.id)
        .limit(ERASE_BATCH)
    )
    if after is not None:
        query = query.where(WorkItem.id > after)
    rows = list((await run.session.scalars(query)).all())
    for record in rows:
        kept = [e for e in record.notify_emails if e.casefold() not in addresses]
        await work_items.set_fields(
            run.session,
            record,
            {"notify_emails": kept},
            expected_version=record.version,
            source="system",
            reason=ERASED_ON_REQUEST,
        )
    last = rows[-1].id if len(rows) == ERASE_BATCH else None
    return ({"notify_addresses_removed": len(rows)} if rows else {}), last


async def _recipients(run: Run, after: uuid.UUID | None) -> tuple[dict[str, int], uuid.UUID | None]:
    """Their address off other conversations' to/cc; the messages stay (lane B, question 4)."""
    addresses = await _addresses(run)
    if not addresses:
        return {}, None
    # Narrowed in SQL to entries naming one of the addresses (escaped: `_` is common in them),
    # then checked exactly here; the batch walks those only, never every conversation.
    named = or_(
        *(
            func.lower(cast(WorkItemConversation.recipients, Text)).contains(a, autoescape=True)
            for a in sorted(addresses)
        )
    )
    query = (
        select(WorkItemConversation)
        .where(WorkItemConversation.recipients.is_not(None), named)
        .order_by(WorkItemConversation.id)
        .limit(ERASE_BATCH)
    )
    if after is not None:
        query = query.where(WorkItemConversation.id > after)
    rows = list((await run.session.scalars(query)).all())
    changed = 0
    for entry in rows:
        recipients: dict[str, Any] = dict(entry.recipients or {})
        stripped = {
            key: [a for a in (value or []) if str(a).casefold() not in addresses]
            for key, value in recipients.items()
            if isinstance(value, list)
        }
        if any(len(stripped[k]) != len(recipients[k] or []) for k in stripped):
            entry.recipients = {**recipients, **stripped}
            changed += 1
    await run.session.flush()
    last = rows[-1].id if len(rows) == ERASE_BATCH else None
    return ({"recipient_addresses_removed": changed} if changed else {}), last


REFERENCE_PHASES: tuple[tuple[str, Batch], ...] = (
    ("follows", _follows),
    ("roles", _role_holds),
    ("chairs", _chairs),
    ("tasks", _tasks),
    ("approvals", _approvals),
    ("kept_informed", _kept_informed),
    ("recipients", _recipients),
)


class References:
    """`work_items.references`: they come off the records that list them (band 100-199)."""

    module: ClassVar[str] = "work_items.references"
    order: ClassVar[int] = 150
    kinds: ClassVar[frozenset[str]] = frozenset(
        {
            "followers_removed",
            "role_holds_removed",
            "board_seats_removed",
            "chairs_handed_over",
            "tasks_unassigned",
            "approvals_rerouted",
            "notify_addresses_removed",
            "recipient_addresses_removed",
        }
    )

    async def erase_person(  # noqa: PLR0913 - the port contract
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """One batch (see the module docstring)."""
        del keep_files, now  # no files or times of their own here
        return await _batched(REFERENCE_PHASES, Run(session, person_id, successor_id), cursor)


# --- owned (550) ----------------------------------------------------------------------------------


def _owned_by(kind: str, handed: str, model: Any) -> Batch:  # noqa: ANN401 - a model
    """Private ones deleted; shared ones (others use them) pass to the successor."""

    async def batch(run: Run, after: uuid.UUID | None) -> tuple[dict[str, int], uuid.UUID | None]:
        query = (
            select(model)
            .where(model.owner_id == run.person_id)
            .order_by(model.id)
            .limit(ERASE_BATCH)
            .with_for_update()
        )
        if after is not None:
            query = query.where(model.id > after)
        rows = list((await run.session.scalars(query)).all())
        private = [r.id for r in rows if r.visibility not in SHARED]
        for row in rows:
            if row.visibility in SHARED:
                row.owner_id = run.successor_id
                row.version += 1
        if private:
            await run.session.execute(delete(model).where(model.id.in_(private)))
        await run.session.flush()
        counts = {kind: len(private), handed: len(rows) - len(private)}
        last = rows[-1].id if len(rows) == ERASE_BATCH else None
        return {k: v for k, v in counts.items() if v}, last

    return batch


async def _drafts(run: Run, after: uuid.UUID | None) -> tuple[dict[str, int], uuid.UUID | None]:
    del after
    count = await drafts.forget_owner(run.session, run.person_id)
    return ({"drafts_deleted": count} if count else {}), None


async def _text_fields(session: AsyncSession, record_type: str) -> frozenset[str]:
    """The record type's free-text custom fields (choices and the like are not their words)."""
    found = await metadata.definitions(session, record_type)
    return frozenset(k for k, d in found.items() if d.type in {FieldType.TEXT, FieldType.LONG_TEXT})


async def _requested(run: Run, after: uuid.UUID | None) -> tuple[dict[str, int], uuid.UUID | None]:
    """The records they requested or were raised for lose the requester's text (D2a).

    The subject keeps a valid value (the reserved marker), the rest is blanked; a record already
    blanked changes nothing. Open ones assigned to them go back to their group's queue.
    """
    query = (
        select(WorkItem)
        .where(
            (WorkItem.requester_id == run.person_id)
            | (WorkItem.on_behalf_of_id == run.person_id)
            | (WorkItem.technician_id == run.person_id)
        )
        .order_by(WorkItem.id)
        .limit(ERASE_BATCH)
        .with_for_update()
    )
    if after is not None:
        query = query.where(WorkItem.id > after)
    rows = list((await run.session.scalars(query)).all())
    blanked = unassigned = 0
    for record in rows:
        columns: dict[str, Any] = {}
        if run.person_id in {record.requester_id, record.on_behalf_of_id}:
            blank: dict[str, Any] = {
                "subject": ERASED_ON_REQUEST,
                "description": None,
                "custom_text": None,
                "answers": {},
            }
            texts = await _text_fields(run.session, record.type)
            custom = {k: (None if k in texts else v) for k, v in (record.custom or {}).items()}
            if custom != (record.custom or {}):
                blank["custom"] = custom
            columns |= {n: v for n, v in blank.items() if getattr(record, n) != v}
            if columns:
                blanked += 1
        if record.technician_id == run.person_id and record.status_category not in {
            c.value for c in FINAL_CATEGORIES
        }:
            columns["technician_id"] = None  # their group keeps it, in its queue
            unassigned += 1
        if columns:
            await work_items.set_fields(
                run.session,
                record,
                columns,
                expected_version=record.version,
                source="system",
                reason=ERASED_ON_REQUEST,
            )
    counts = {"requests_blanked": blanked, "records_unassigned": unassigned}
    last = rows[-1].id if len(rows) == ERASE_BATCH else None
    return {k: v for k, v in counts.items() if v}, last


OWNED_PHASES: tuple[tuple[str, Batch], ...] = (
    (
        "list_settings",
        _deleting(
            "work_item_list_settings_deleted", WorkItemListSetting, WorkItemListSetting.user_id
        ),
    ),
    ("reminders", _deleting("reminders_deleted", WorkItemReminder, WorkItemReminder.user_id)),
    ("timers", _deleting("timers_deleted", WorkItemTimer, WorkItemTimer.user_id)),
    ("drafts", _drafts),
    ("views", _owned_by("views_deleted", "views_handed_over", WorkItemView)),
    (
        "reply_templates",
        _owned_by("reply_templates_deleted", "reply_templates_handed_over", WorkItemReplyTemplate),
    ),
    ("requested", _requested),
)


class Owned:
    """`work_items.owned`: their private rows and the records they requested (band 500-599)."""

    module: ClassVar[str] = "work_items.owned"
    order: ClassVar[int] = 550
    kinds: ClassVar[frozenset[str]] = frozenset(
        {
            "work_item_list_settings_deleted",
            "reminders_deleted",
            "timers_deleted",
            "drafts_deleted",
            "views_deleted",
            "views_handed_over",
            "reply_templates_deleted",
            "reply_templates_handed_over",
            "requests_blanked",
            "records_unassigned",
        }
    )

    async def erase_person(  # noqa: PLR0913 - the port contract
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """One batch (see the module docstring)."""
        del keep_files, now  # files are the files module's (uploads), times are not needed
        return await _batched(OWNED_PHASES, Run(session, person_id, successor_id), cursor)


REFERENCES = References()
OWNED = Owned()


def register() -> None:
    """Both ports, at import (the registry refuses the job while one is missing)."""
    register_person_data(REFERENCES)
    register_person_data(OWNED)


__all__ = ["OWNED", "REFERENCES", "Owned", "References", "register"]
