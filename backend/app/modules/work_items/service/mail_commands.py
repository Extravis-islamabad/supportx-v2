"""Applying the commands at the top of a mail to the incident it makes (WP-046a S6; REQ-INC-025).

The coordinator's conditions (2026-11-13):

1. Commands apply only for a type whose settings turn them on (off by default), for the fields the
   settings allow, and only when the mailbox's trusted server vouched for the sender
   (`InboundMessage.sender_verified`, lane B's parser). Otherwise the block stays plain text; when
   it was only the sender who was not verified, the record's history says so.
2. No new right: each line goes through the same service call the API uses, as the sender, with
   the sender's own rights (category and priority: `update`; group and technician: `assign`, so
   D-154's group rule holds; template: offered to the sender at create). A refusal skips the line.
3. A line that cannot be applied is reported to the sender; the incident is made either way.
"""

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.logging import get_logger
from app.modules.identity_access import Subject, mail_recipients, person_by_email
from app.modules.organization import find_group
from app.modules.work_items.domain.mail_commands import (
    Block,
    Command,
    CommandField,
    LineProblem,
    Rejected,
    read_block,
)
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemCategory,
    WorkItemTypeSettings,
)
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import templates
from app.shared.history import Change, record_changes
from app.shared.labels import LANGUAGES, has_label, plain_label

if TYPE_CHECKING:
    from app.modules.work_items.service.work_items import PermissionHolders

log = get_logger(__name__)
FIELD = "mail_commands"  # the history line: "commands in this e-mail were not applied: …"
NOT_VERIFIED = "not_verified"


@dataclass(frozen=True)
class Settings:
    """A type's mail command settings."""

    enabled: bool
    fields: frozenset[CommandField]


async def settings_of(session: AsyncSession, wtype: WorkItemType) -> Settings:
    """Whether the type takes commands from mail, and for which fields."""
    row = (
        await session.execute(
            select(
                WorkItemTypeSettings.mail_commands, WorkItemTypeSettings.mail_command_fields
            ).where(WorkItemTypeSettings.type == wtype.code)
        )
    ).one_or_none()
    if row is None:
        return Settings(enabled=False, fields=frozenset())
    allowed = frozenset(CommandField(f) for f in row.mail_command_fields if f in CommandField)
    return Settings(bool(row.mail_commands), allowed)


@dataclass(frozen=True)
class Plan:
    """What to do with a mail's block: the commands to try, and lines already refused."""

    block: Block
    not_verified: bool  # there were commands, but the sender was not vouched for

    @property
    def commands(self) -> tuple[Command, ...]:
        """The commands to try (none when the sender was not verified)."""
        return () if self.not_verified else self.block.commands

    @property
    def rejected(self) -> tuple[Rejected, ...]:
        """Lines known not to apply before trying (none when nothing is tried)."""
        return () if self.not_verified else self.block.rejected


async def plan(
    session: AsyncSession, wtype: WorkItemType, text: str, *, sender_verified: bool
) -> Plan | None:
    """The mail's commands for this type, or None when the type takes none or there are none."""
    found = await settings_of(session, wtype)
    if not found.enabled:
        return None  # the block is plain text, as for any mail
    block = read_block(text, found.fields)
    if block.empty:
        return None
    return Plan(block, not_verified=not sender_verified)


def _names(code: str | None, labels: Mapping[str, str] | None, prefix: str) -> set[str]:
    """Every name a value goes by: its own per language, or its shipped label's, and its code."""
    names = {v.strip().lower() for v in (labels or {}).values() if v}
    if code:
        names.add(code.lower())
        key = f"{prefix}.{code}"
        if has_label(key):
            names |= {plain_label(key, language).strip().lower() for language in LANGUAGES}
    return names


def _one(matches: Iterable[uuid.UUID]) -> uuid.UUID | None:
    found = list(dict.fromkeys(matches))
    return found[0] if len(found) == 1 else None


async def _category(session: AsyncSession, wtype: WorkItemType, value: str) -> uuid.UUID | None:
    wanted = value.strip().lower()
    rows = await session.execute(
        select(WorkItemCategory.id, WorkItemCategory.code, WorkItemCategory.labels).where(
            WorkItemCategory.type == wtype.code,
            WorkItemCategory.deleted_at.is_(None),
            WorkItemCategory.disabled_at.is_(None),
        )
    )
    return _one(
        row.id for row in rows if wanted in _names(row.code, row.labels, "work_item_category")
    )


async def _priority(session: AsyncSession, wtype: WorkItemType, value: str) -> str | None:
    wanted = value.strip().lower()
    cat = await config.load(session, wtype)
    found = [
        s.code
        for s in cat.scales
        if s.scale == "priority" and wanted in _names(s.code, s.labels, "priority")
    ]
    return found[0] if len(found) == 1 else None


async def template_for(
    session: AsyncSession, wtype: WorkItemType, sender: Subject, value: str
) -> uuid.UUID | None:
    """The enabled template the sender is offered by that name, or None."""
    wanted = value.strip().lower()
    offered = await templates.offered_to(
        session,
        sender,
        [t for t in await templates.list_templates(session, wtype) if t.disabled_at is None],
    )
    return _one(t.id for t in offered if wanted in _names(t.code, t.labels, "incident_template"))


@dataclass(frozen=True)
class TemplateChoice:
    """The template a mail names, applied at create: its ID, or why the line was not applied."""

    template_id: uuid.UUID | None = None
    rejected: tuple[Rejected, ...] = ()


async def template_choice(
    session: AsyncSession, wtype: WorkItemType, sender: Subject, planned: Plan | None
) -> TemplateChoice:
    """`template = …` among the templates the sender is offered (as the create form offers)."""
    for command in planned.commands if planned is not None else ():
        if command.field is CommandField.TEMPLATE:
            found = await template_for(session, wtype, sender, command.value)
            if found is not None:
                return TemplateChoice(found)
            text = f"{command.field} = {command.value}"
            return TemplateChoice(rejected=(Rejected(command.line, text, LineProblem.NOT_FOUND),))
    return TemplateChoice()


@dataclass(frozen=True)
class Outcome:
    """What became of a mail's commands, for the history, the ledger and the sender's answer."""

    applied: tuple[int, ...] = ()  # line numbers
    rejected: tuple[Rejected, ...] = ()
    not_verified: bool = False


async def _try(session: AsyncSession, work: Any) -> bool:  # noqa: ANN401 - a coroutine
    """Run one service call in a savepoint; False (and nothing kept) when it refuses."""
    try:
        async with session.begin_nested():
            await work
    except AppError as refused:
        log.info("mail_command_refused", code=refused.code)  # never the mail's text
        return False
    return True


@dataclass
class _Run:
    """One mail's commands being applied to its new record, as the sender."""

    session: AsyncSession
    wtype: WorkItemType
    record: WorkItem
    sender: Subject
    holders: "PermissionHolders"
    applied: list[int] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)

    def refuse(self, command: Command, problem: LineProblem) -> None:
        self.rejected.append(Rejected(command.line, f"{command.field} = {command.value}", problem))

    async def done(self, commands: list[Command], ok: bool) -> None:  # noqa: FBT001 - one flag
        if ok:
            await self.session.refresh(self.record)
            self.applied.extend(c.line for c in commands)
        else:
            for command in commands:
                self.refuse(command, LineProblem.REFUSED)


async def _fields(run: _Run, by_field: Mapping[CommandField, Command]) -> None:
    """Category and priority, one at a time, through the API's edit (the sender's rights)."""
    from app.modules.work_items.service import work_items as items  # noqa: PLC0415 - cycle

    lookups = (
        (CommandField.CATEGORY, "category_id", _category),
        (CommandField.PRIORITY, "priority", _priority),
    )
    for wanted, name, lookup in lookups:
        command = by_field.get(wanted)
        if command is None:
            continue
        value = await lookup(run.session, run.wtype, command.value)
        if value is None:
            run.refuse(command, LineProblem.NOT_FOUND)
            continue
        change: dict[str, Any] = {name: value}
        if name == "priority":  # a priority set by hand says why, as the API asks (REQ-INC-008)
            change["priority_reason"] = await _priority_reason(run)
        work = items.update(
            run.session,
            run.sender,
            run.wtype,
            run.record.id,
            expected_version=run.record.version,
            values=change,
            source="email",
        )
        await run.done([command], await _try(run.session, work))


async def _priority_reason(run: _Run) -> str:
    """The reason a priority set by mail carries, in the sender's language."""
    known = await mail_recipients(run.session, [run.sender.user_id])
    language = known[run.sender.user_id].language if run.sender.user_id in known else "en"
    return plain_label("mail_commands.priority_reason", language)


async def _assignment(run: _Run, by_field: Mapping[CommandField, Command]) -> None:
    """Group and technician together, through the API's assignment (D-154's group rule holds)."""
    from app.modules.work_items.service import work_items as items  # noqa: PLC0415 - cycle

    group_id, technician_id = run.record.group_id, run.record.technician_id
    using: list[Command] = []
    if (command := by_field.get(CommandField.GROUP)) is not None:
        group_id = await find_group(run.session, command.value)
        if group_id is None:
            run.refuse(command, LineProblem.NOT_FOUND)
            group_id = run.record.group_id
        else:
            using.append(command)
    if (command := by_field.get(CommandField.TECHNICIAN)) is not None:
        found = await person_by_email(run.session, command.value.strip().lower())
        if found is None:
            run.refuse(command, LineProblem.NOT_FOUND)
        else:
            technician_id = found
            using.append(command)
    if not using:
        return
    work = items.assign(
        run.session,
        run.sender,
        run.wtype,
        run.record.id,
        expected_version=run.record.version,
        group_id=group_id,
        technician_id=technician_id,
        reason_code=None,
        reason_text=None,
        confirm_lose_access=True,
        source="email",
        holders=run.holders,
    )
    await run.done(using, await _try(run.session, work))


async def apply(
    run_in: tuple[AsyncSession, WorkItemType, WorkItem, Subject, "PermissionHolders"],
    commands: Iterable[Command],
) -> tuple[tuple[int, ...], tuple[Rejected, ...]]:
    """Each command through the API's own service call, as the sender; (applied, rejected).

    `run_in`: the session, the type, the new record, the sender and the worker's permissions.
    """
    run = _Run(*run_in)
    by_field = {c.field: c for c in commands}
    await _fields(run, by_field)
    await _assignment(run, by_field)
    return tuple(sorted(run.applied)), tuple(sorted(run.rejected, key=lambda r: r.line))


async def note_not_verified(session: AsyncSession, record: WorkItem) -> None:
    """The record's history says its mail's commands were not applied, and why (lane B, 7)."""
    await record_changes(
        session,
        record_type=record.type,
        record_id=record.id,
        version=record.version,
        kind="updated",
        changes=[Change(FIELD, None, NOT_VERIFIED)],
        source="email",
    )
