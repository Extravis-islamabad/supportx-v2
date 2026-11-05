"""Messages from a problem (WP-044b s4; REQ-PRB-052).

- `recipients`: the people a message may go to, as a set the composer offers by name:
  - the problem's followers;
  - the technicians of the incidents it causes;
  - those incidents' requesters.
  Only incidents the sender may see count, so the set never names someone from a hidden
  record. The composer sends to their addresses through the problem's own reply (the
  conversation engine: kept on the timeline with its delivery state).
- `to_incident_requesters`: one message to everyone affected, sent as a public reply on each
  linked incident the sender may reply on, so it reaches that incident's requester in the usual
  way. It lands on each incident's timeline with its own delivery state, and the problem's
  history names the incidents. An incident the sender may not reply on is skipped and named.
"""

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
from app.modules.identity_access import Subject, user_contacts
from app.modules.work_items.domain.conversation import EntryKind, Visibility
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.types import INCIDENT, PROBLEM
from app.modules.work_items.infra.models import WorkItem, WorkItemLink
from app.modules.work_items.service import conversations, followers, problems
from app.modules.work_items.service import work_items as items
from app.shared.history import Change, Source, record_changes


class RecipientSet(StrEnum):
    """Who a problem's message may go to, by set (REQ-PRB-052)."""

    FOLLOWERS = "followers"
    INCIDENT_TECHNICIANS = "incident_technicians"
    INCIDENT_REQUESTERS = "incident_requesters"


@dataclass(frozen=True)
class Recipient:
    """One person of a set: who, and the address a message goes to."""

    user_id: uuid.UUID
    name: str
    email: str


async def _visible_incidents(
    session: AsyncSession, subject: Subject, problem_id: uuid.UUID
) -> list[WorkItem]:
    caused = select(WorkItemLink.source_id).where(
        WorkItemLink.target_id == problem_id,
        WorkItemLink.kind == LinkKind.CAUSED_BY.value,
        WorkItemLink.deleted_at.is_(None),
    )
    return list(
        await session.scalars(
            items.staff_rows(subject, INCIDENT)
            .where(WorkItem.id.in_(caused))
            .order_by(WorkItem.created_at, WorkItem.id)
        )
    )


async def recipients(
    session: AsyncSession, subject: Subject, problem_id: uuid.UUID, which: RecipientSet
) -> list[Recipient]:
    """The set's people with an address, by name (404 when the problem is not visible)."""
    await problems.problem_of(session, subject, problem_id)
    people: list[uuid.UUID] = []
    if which is RecipientSet.FOLLOWERS:
        people = [f.user_id for f in await followers.of_record(session, problem_id)]
    else:
        for incident in await _visible_incidents(session, subject, problem_id):
            if which is RecipientSet.INCIDENT_TECHNICIANS and incident.technician_id:
                people.append(incident.technician_id)
            if which is RecipientSet.INCIDENT_REQUESTERS:
                people += [p for p in (incident.requester_id, incident.on_behalf_of_id) if p]
    wanted = list(dict.fromkeys(people))
    contacts = await user_contacts(session, [str(p) for p in wanted])
    found = [
        Recipient(p, contacts[str(p)][0], contacts[str(p)][1])
        for p in wanted
        if str(p) in contacts and contacts[str(p)][1]
    ]
    return sorted(found, key=lambda r: r.name.lower())


@dataclass
class Sent:
    """Where the requesters' message went, and where it could not."""

    incidents: list[WorkItem] = field(default_factory=list)
    skipped: list[uuid.UUID] = field(default_factory=list)


async def to_incident_requesters(  # noqa: PLR0913 - the problem, the text and the context
    session: AsyncSession,
    subject: Subject,
    problem_id: uuid.UUID,
    *,
    body: str,
    source: Source,
    policy: conversations.ReplyPolicy,
) -> Sent:
    """A public reply on each linked incident the sender may reply on (REQ-PRB-052 AC3)."""
    problem = await problems.problem_of(session, subject, problem_id)
    if not await items.may(session, subject, PROBLEM, "edit", problem.id):
        raise PermissionDenied(params={"permission": PROBLEM.permission("edit")})
    sent = Sent()
    for incident in await _visible_incidents(session, subject, problem_id):
        try:
            async with session.begin_nested():
                await conversations.add_entry(
                    session,
                    subject,
                    INCIDENT,
                    incident.id,
                    kind=EntryKind.REPLY,
                    visibility=Visibility.PUBLIC,
                    body=body,
                    reply_mode=None,
                    to=[],
                    cc=[],
                    source=source,
                    policy=policy,
                )
            sent.incidents.append(incident)
        except (PermissionDenied, NotFound):
            sent.skipped.append(incident.id)
    if sent.incidents:
        await record_changes(
            session,
            record_type=followers.RECORD_TYPE,
            record_id=problem.id,
            version=problem.version,
            kind="child_added",
            changes=[
                Change(
                    "requester_message",
                    None,
                    {"incidents": [i.display_id for i in sent.incidents]},
                )
            ],
            source=source,
        )
    return sent
