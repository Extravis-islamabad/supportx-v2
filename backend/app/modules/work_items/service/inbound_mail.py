"""Incidents from mail: the work items side of the inbound port (WP-024; REQ-INC-023).

`integrations` reads mailboxes and decides what a message is; this module owns what it does to an
incident (`app.shared.mail.ports.InboundTarget`):

- `find_record`: the incident a message answers, by its token ("[INC-12]", old prefixes too) or
  by the incidents of the notification e-mails it answers;
- `reply_from_mail`: the requester's public reply through `add_requester_reply`, so the record
  moves as for any requester reply (WP-020f) and an automatic reply only records itself;
- `create_from_mail`: a new incident in the requester's name, channel "email".

Mail runs in a worker, so the requester's subject is compiled now and the policy is the worker's
(`identity_access.subject_for`, `worker_policy`): the same decisions as in the API.
"""

import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import AppError, ValidationFailed
from app.core.tenancy import TenantContext
from app.modules.identity_access import mail_recipients, subject_for, worker_policy
from app.modules.work_items.domain import kept_informed
from app.modules.work_items.domain.mail_commands import CommandField
from app.modules.work_items.domain.types import INCIDENT, SUBJECT_MAX, Channel, parse_display_id
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import asset_links, catalogue, mail_commands
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.conversations import add_requester_reply
from app.shared.labels import label
from app.shared.mail.ports import (
    CommandLine,
    CreatedRecord,
    FoundRecord,
    InboundRefused,
    Replied,
    register_inbound_target,
    unregister_inbound_target,
)

RECORD_TYPE = INCIDENT.code.value


def _tenant(session: AsyncSession) -> uuid.UUID:
    context = session.info[SESSION_TENANT_KEY]
    if not isinstance(context, TenantContext):  # pragma: no cover - a tenant session always
        msg = "mail is handled in a tenant session"
        raise TypeError(msg)
    return context.tenant_id


# A create refused for missing or invalid fields: the admin's review queue names them (their
# `field.<name>` labels), so they know what the template or rule asks for (D-109 (9)).
FIELDS_NEEDED = "mail_fields_needed"


@asynccontextmanager
async def _refusals() -> AsyncIterator[None]:
    """An expected refusal of the incident side, as the port's InboundRefused (held, not lost)."""
    try:
        yield
    except ValidationFailed as refused:
        fields = sorted({e.field.removeprefix("body.") for e in refused.errors})
        if fields:
            raise InboundRefused(FIELDS_NEEDED, {"fields": ",".join(fields)}) from refused
        raise InboundRefused(refused.instance_code, _text(refused.params)) from refused
    except AppError as refused:
        if refused.status >= 500:  # noqa: PLR2004 - an outage is retried, never held
            raise
        raise InboundRefused(refused.instance_code, _text(refused.params)) from refused


def fit_subject(text: str) -> str:
    """A mail subject as an incident subject: one line, at most SUBJECT_MAX characters.

    Longer ones are cut on a word boundary with an ellipsis (lane A review, #109): a long subject
    must create the incident, not be held for it. "" when there is nothing to keep.
    """
    one_line = " ".join(text.split())
    if len(one_line) <= SUBJECT_MAX:
        return one_line
    cut = one_line[: SUBJECT_MAX - 1]
    space = cut.rfind(" ")
    if space > SUBJECT_MAX // 2:  # a word boundary not too far back; else cut the long word
        cut = cut[:space]
    return cut.rstrip() + "…"


def _text(params: Mapping[str, object]) -> dict[str, str]:
    return {key: str(value) for key, value in params.items()}


def _found(row: WorkItem) -> FoundRecord:
    people = {row.requester_id, row.on_behalf_of_id} - {None}
    return FoundRecord(RECORD_TYPE, row.id, row.display_id, frozenset(p for p in people if p))


async def _by_token(session: AsyncSession, token: str) -> WorkItem | None:
    cat = await catalogue.load(session, INCIDENT)
    prefix, number = parse_display_id(token, cat.prefix)
    if number is None:
        return None
    row = await session.scalar(
        select(WorkItem).where(
            WorkItem.type == RECORD_TYPE,
            WorkItem.deleted_at.is_(None),
            WorkItem.display_number == number,
        )
    )
    if row is None:
        return None
    # The incident's own prefix, or today's (an old prefix keeps working, REQ-WI-002).
    if prefix is not None and prefix not in {row.display_id.rsplit("-", 1)[0], cat.prefix}:
        return None
    return row


async def _kept_informed(
    session: AsyncSession, requester_id: uuid.UUID, cc: Sequence[str]
) -> list[str]:
    """The first mail's Cc kept informed (REQ-INC-066), when the type says so.

    Never the requester's own address: they hear as the requester.
    """
    if not cc:
        return []
    cat = await catalogue.load(session, INCIDENT)
    if not cat.cc_from_first_mail:
        return []
    known = await mail_recipients(session, [requester_id])
    mine = known[requester_id].email if requester_id in known else None
    return kept_informed.from_first_mail(cc, excluded=[mine] if mine else [])


class IncidentsFromMail:
    """`InboundTarget` for incidents."""

    record_type = RECORD_TYPE

    async def find_record(
        self, session: AsyncSession, *, tokens: Sequence[str], record_ids: Sequence[uuid.UUID]
    ) -> FoundRecord | None:
        """The incident named in the subject, else the one the answered mail was about."""
        for token in tokens:
            if (row := await _by_token(session, token)) is not None:
                return _found(row)
        if record_ids:
            row = await session.scalar(
                select(WorkItem).where(
                    WorkItem.type == RECORD_TYPE,
                    WorkItem.deleted_at.is_(None),
                    WorkItem.id.in_(list(record_ids)),
                )
            )
            if row is not None:
                return _found(row)
        return None

    async def create_from_mail(  # noqa: PLR0913 - the port's fields, explicit
        self,
        session: AsyncSession,
        *,
        requester_id: uuid.UUID,
        subject: str,
        body_html: str,
        group_id: uuid.UUID | None,
        message_id: str,
        text: str = "",
        sender_verified: bool = False,
        cc: Sequence[str] = (),
    ) -> CreatedRecord:
        """A new incident in the requester's name, channel e-mail, routed with the mailbox's group.

        Created as the requester would in the portal (their own rights, priority, routing and
        automation as for any new record); the mailbox's group is the entry point's group.
        Commands at the top of the mail (REQ-INC-025) apply as the sender, see mail_commands.
        """
        del message_id  # the ledger keeps it
        requester = await subject_for(session, _tenant(session), requester_id)
        planned = await mail_commands.plan(session, INCIDENT, text, sender_verified=sender_verified)
        template = await mail_commands.template_choice(session, INCIDENT, requester, planned)
        values: dict[str, object] = (
            {} if template.template_id is None else {"template_id": template.template_id}
        )
        # The Cc join only when the sender was vouched for (lane B's #485 review): a forged From
        # with an attacker in Cc would otherwise copy every public reply to the attacker.
        kept = await _kept_informed(session, requester_id, cc)
        cc_set_aside = bool(kept) and not sender_verified
        if kept and sender_verified:
            values["notify_emails"] = kept
        title = fit_subject(subject)
        if not title:  # neither a subject nor any text: a stored name, in the requester's language
            known = await mail_recipients(session, [requester_id])
            language = known[requester_id].language if requester_id in known else "en"
            title = label("incidents.mail_no_subject", language)
        async with _refusals():
            made = await items.create(
                session,
                requester,
                INCIDENT,
                {
                    "subject": title,
                    "description": body_html,
                    "requester_id": requester_id,
                    **values,
                },
                source="email",
                holders=worker_policy(),
                channel=Channel.EMAIL,
                entry_group_id=group_id,
            )
        # REQ-AST-025 AC2: the requester's asset when the tenant says so and they hold one.
        await asset_links.attach_emailed(session, made.record)
        if cc_set_aside:  # said in the history, never naming the addresses
            await mail_commands.note_cc_not_verified(session, made.record)
        if planned is None:
            return CreatedRecord(RECORD_TYPE, made.record.id, made.record.display_id)
        if planned.not_verified:
            await mail_commands.note_not_verified(session, made.record)
            return CreatedRecord(
                RECORD_TYPE, made.record.id, made.record.display_id, commands_not_verified=True
            )
        applied, refused = await mail_commands.apply(
            (session, INCIDENT, made.record, requester, worker_policy()),
            [c for c in planned.commands if c.field is not CommandField.TEMPLATE],
        )
        not_applied = sorted(
            [*planned.rejected, *template.rejected, *refused], key=lambda r: r.line
        )
        return CreatedRecord(
            RECORD_TYPE,
            made.record.id,
            made.record.display_id,
            commands_applied=len(applied) + (template.template_id is not None),
            commands_not_applied=tuple(
                CommandLine(r.line, r.text, r.problem.value) for r in not_applied
            ),
        )

    async def reply_from_mail(  # noqa: PLR0913 - the port's fields, explicit
        self,
        session: AsyncSession,
        record: FoundRecord,
        *,
        author_id: uuid.UUID,
        body_html: str,
        automatic: bool,
        message_id: str,
    ) -> Replied:
        """The requester's reply; the follow-up incident when the record was closed too long."""
        del message_id  # the ledger keeps it; the entry is the reply itself
        row = await session.get(WorkItem, record.record_id)
        if row is None:  # pragma: no cover - found in this transaction
            return Replied(entry_id=None)
        subject = await subject_for(session, _tenant(session), author_id)
        async with _refusals():
            replied = await add_requester_reply(
                session,
                INCIDENT,
                row,
                body=body_html,
                source="email",
                automatic=automatic,
                subject=subject,
                holders=worker_policy(),
            )
        # The reply's attachments go on its entry (WP-024 session 2).
        follow_up = replied.follow_up
        if follow_up is None:
            return Replied(entry_id=replied.entry_id)
        return Replied(
            entry_id=replied.entry_id,
            follow_up=CreatedRecord(RECORD_TYPE, follow_up.id, follow_up.display_id),
        )


TARGET = IncidentsFromMail()


def register() -> None:
    """Incidents take mail in (at import, so the worker that fetches mailboxes has it too)."""
    register_inbound_target(TARGET)


def unregister() -> None:
    """For tests that register their own target."""
    unregister_inbound_target(RECORD_TYPE)
