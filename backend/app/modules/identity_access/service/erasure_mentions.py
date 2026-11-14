"""The mentions report of a person erasure, its review and redaction (D-171 a, ADR-052 S1b).

- **Build** (the erasure schedule, while the erasure is requested): every registered mentions
  port, in registry order, in bounded batches, one transaction each. Found places go into
  `person_erasure_mentions`; progress (port and cursor) is kept in `report.building`, so a
  stopped build resumes there. When every registered port has run, `report` holds the summary
  `{complete, by_module: {key: {kind: count}}, ports_done, ports_missing,
  attachment_content_searched: false, building: null}`. `complete` only when every key in
  REQUIRED_MENTION_PORTS has run. A port registered later (a new release) runs on the next
  schedule tick, and the finished report then needs a fresh review.
- **Review:** an admin marks the finished report reviewed (If-Match); approval needs it.
- **Passage:** the field's current text, only through the owning port, which checks the
  caller's own rights to read that record (None: 404). The route audits each view.
- **Redaction:** the owning port replaces the matched occurrences of the chosen mentions with
  the D2a marker; only before the job starts (requested or approved). The route audits each.
- **Approval** (service/erasure.py) leaves every mention still found as `left`.

Attachment contents are never searched (only file names): the report says so with the fixed
flag `attachment_content_searched: false`, which the screens label.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, NotFound
from app.modules.identity_access.domain import erasure as rules
from app.modules.identity_access.domain.erasure import ErasureState
from app.modules.identity_access.domain.field_access import unseen
from app.modules.identity_access.domain.mentions import (
    MentionMatchKind,
    MentionState,
    MentionTerms,
    build_terms,
)
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.events import PersonErasureChanged
from app.modules.identity_access.infra.models import PersonErasure, PersonErasureMention, User
from app.modules.identity_access.service.person_data import (
    Mention,
    PersonMentions,
    mention_port,
    mention_ports,
    missing_mention_ports,
)
from app.shared.db.repository import decode_cursor, encode_cursor
from app.shared.erasure import ERASED_ON_REQUEST
from app.shared.events import record_event
from app.shared.history import stale_version
from app.shared.ids import new_id

ATTACHMENT_CONTENT_SEARCHED = False  # only file names and details are searched, never contents
ATTACHMENT_NOTICE_LABEL = "people_erasure.attachment_content_not_searched"
# Inbound mail: subjects only, never bodies (raw MIME leaves at quarantine expiry); said to the
# approver as for attachments (the coordinator, 2026-11-14).
MAIL_BODIES_SEARCHED = False
MAIL_NOTICE_LABEL = "people_erasure.mail_bodies_not_searched"
LIST_LIMIT = 200
REDACT_MAX = 200
CURSOR_MAX = 2000  # a port's cursor, as the erasure ports'


def person_terms(person: User) -> MentionTerms:
    """The person's search terms, from their row as it is now (never stored)."""
    return build_terms(
        display_name=person.display_name,
        first_name=person.first_name,
        last_name=person.last_name,
        email=person.email,
        phone=person.phone,
        mobile=person.mobile,
    )


def _mention(row: PersonErasureMention) -> Mention:
    return Mention(
        record_type=row.record_type,
        record_id=row.record_id,
        field=row.field,
        match_kind=MentionMatchKind(row.match_kind),
        occurrences=row.occurrences,
    )


async def _changed(session: AsyncSession, row: PersonErasure) -> None:
    await record_event(
        session,
        PersonErasureChanged(person_id=row.person_id, state=row.state, step=row.step),  # type: ignore[arg-type]  # a checked state code
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


def report_complete(report: dict[str, Any] | None) -> bool:
    """Whether the report has finished and every required port ran (approval needs it)."""
    if report is None:
        return False
    return report.get("building") is None and report.get("complete") is True


def report_finished(report: dict[str, Any] | None) -> bool:
    """Whether a build pass has finished (complete or not): it can be reviewed."""
    return report is not None and report.get("building") is None


def _done(report: dict[str, Any] | None) -> list[str]:
    return [str(key) for key in (report or {}).get("ports_done", [])]


def needs_build(row: PersonErasure) -> bool:
    """A requested erasure whose report is missing, mid-way, or lacks a registered port."""
    if row.state != ErasureState.REQUESTED.value:
        return False
    report = row.report
    if report is None or report.get("building") is not None:
        return True
    done = set(_done(report))
    return any(port.module not in done for port in mention_ports())


async def reports_due(session: AsyncSession, now: datetime) -> list[uuid.UUID]:
    """The tenant's requested erasures whose report needs (more) building."""
    rows = await session.scalars(
        select(PersonErasure).where(
            PersonErasure.state == ErasureState.REQUESTED.value,
            PersonErasure.expires_at > now,
        )
    )
    return [row.id for row in rows if needs_build(row)]


async def _counts(session: AsyncSession, erasure_id: uuid.UUID, module: str) -> dict[str, int]:
    found = await session.execute(
        select(PersonErasureMention.match_kind, func.count())
        .where(
            PersonErasureMention.erasure_id == erasure_id,
            PersonErasureMention.module_key == module,
        )
        .group_by(PersonErasureMention.match_kind)
    )
    return {str(kind): int(count) for kind, count in found.all()}


async def _insert(
    session: AsyncSession, row: PersonErasure, module: str, mentions: Sequence[Mention]
) -> None:
    if not mentions:
        return
    tenant = session.info[SESSION_TENANT_KEY].tenant_id
    await session.execute(
        insert(PersonErasureMention)
        .values(
            [
                {
                    "tenant_id": tenant,
                    "id": new_id(),
                    "erasure_id": row.id,
                    "module_key": module,
                    "record_type": mention.record_type,
                    "record_id": mention.record_id,
                    "field": mention.field,
                    "match_kind": mention.match_kind.value,
                    "occurrences": mention.occurrences,
                    "state": MentionState.FOUND.value,
                }
                for mention in mentions
                if mention.occurrences > 0
            ]
        )
        .on_conflict_do_nothing(constraint="uq_person_erasure_mentions_place")
    )


async def _finish(
    session: AsyncSession, row: PersonErasure, report: dict[str, Any], *, changed: bool
) -> None:
    done = _done(report)
    report.update(
        building=None,
        ports_missing=missing_mention_ports(set(done)),
        complete=not missing_mention_ports(set(done)),
        attachment_content_searched=ATTACHMENT_CONTENT_SEARCHED,
        mail_bodies_searched=MAIL_BODIES_SEARCHED,
    )
    row.report = report
    if changed:  # what the reviewer saw is no longer the whole report
        row.report_reviewed_at = row.report_reviewed_by = None
    row.version += 1
    await session.flush()
    await _changed(session, row)


async def build_report_batch(session: AsyncSession, erasure_id: uuid.UUID) -> bool:
    """One batch of the report build for one erasure. True: call again (in a new transaction)."""
    row = await session.scalar(
        select(PersonErasure).where(PersonErasure.id == erasure_id).with_for_update()
    )
    if row is None or not needs_build(row):
        return False
    report: dict[str, Any] = dict(row.report or {})
    report.setdefault("by_module", {})
    report.setdefault("ports_done", [])
    report["complete"] = False
    report["attachment_content_searched"] = ATTACHMENT_CONTENT_SEARCHED
    report["mail_bodies_searched"] = MAIL_BODIES_SEARCHED
    building = report.get("building")
    done = _done(report)
    port = mention_port(str(building["port"])) if building else None
    cursor = str(building["cursor"]) if building and building.get("cursor") else None
    if port is None:  # nothing under way (or its port went away): the next one not done
        cursor = None
        port = next((p for p in mention_ports() if p.module not in done), None)
    if port is None:
        await _finish(session, row, report, changed=row.report is None)
        return False
    person = await session.get(User, row.person_id)
    terms = person_terms(person) if person is not None else MentionTerms()
    if terms.empty():
        batch_cursor: str | None = None
    else:
        batch = await port.find_mentions(session, row.person_id, terms=terms, cursor=cursor)
        await _insert(session, row, port.module, batch.mentions)
        batch_cursor = batch.cursor
    if batch_cursor is not None:
        if len(batch_cursor) > CURSOR_MAX:
            msg = "a mentions port's cursor is too long"
            raise ValueError(msg)
        report["building"] = {"port": port.module, "cursor": batch_cursor}
        row.report = report
        await session.flush()
        return True
    report["ports_done"] = sorted({*done, port.module})
    report["by_module"] = {
        **report["by_module"],
        port.module: await _counts(session, row.id, port.module),
    }
    report["building"] = None
    remaining = [p for p in mention_ports() if p.module not in report["ports_done"]]
    if remaining:
        report["building"] = {"port": remaining[0].module, "cursor": None}
        row.report = report
        await session.flush()
        return True
    await _finish(session, row, report, changed=True)
    return False


async def _locked(
    session: AsyncSession, erasure_id: uuid.UUID, expected_version: int
) -> PersonErasure:
    row = await session.scalar(
        select(PersonErasure).where(PersonErasure.id == erasure_id).with_for_update()
    )
    if row is None:
        raise NotFound(code=rules.NOT_FOUND)
    if row.version != expected_version:
        raise await stale_version(session, row, expected_version=expected_version)
    return row


async def mark_reviewed(
    session: AsyncSession,
    actor_id: uuid.UUID,
    erasure_id: uuid.UUID,
    *,
    expected_version: int,
    now: datetime,
) -> PersonErasure:
    """An admin reviewed the finished report (approval needs it)."""
    row = await _locked(session, erasure_id, expected_version)
    if not rules.can("review", ErasureState(row.state)).allowed:
        raise Conflict(code=rules.NOT_PENDING, params={"state": row.state})
    if not report_finished(row.report):
        raise Conflict(code=rules.REPORT_UNAVAILABLE)
    row.report_reviewed_at, row.report_reviewed_by = now, actor_id
    row.version += 1
    await session.flush()
    await _changed(session, row)
    return row


async def leave_found(session: AsyncSession, erasure_id: uuid.UUID) -> int:
    """At approval: every mention still found is left in place (the approver saw it)."""
    result = await session.execute(
        update(PersonErasureMention)
        .where(
            PersonErasureMention.erasure_id == erasure_id,
            PersonErasureMention.state == MentionState.FOUND.value,
        )
        .values(state=MentionState.LEFT.value, version=PersonErasureMention.version + 1)
        .execution_options(synchronize_session=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


@dataclass(frozen=True)
class MentionPage:
    """One page of an erasure's mentions, oldest first, and the cursor of the next."""

    items: list[PersonErasureMention]
    next_cursor: str | None


async def list_mentions(
    session: AsyncSession,
    erasure_id: uuid.UUID,
    *,
    cursor: str | None,
    limit: int = LIST_LIMIT,
) -> tuple[PersonErasure, MentionPage]:
    """The erasure and one page of its mentions (404 for an erasure not found)."""
    row = await session.get(PersonErasure, erasure_id)
    if row is None:
        raise NotFound(code=rules.NOT_FOUND)
    query = select(PersonErasureMention).where(PersonErasureMention.erasure_id == erasure_id)
    if cursor:
        query = query.where(PersonErasureMention.id > decode_cursor(cursor))
    found = list(await session.scalars(query.order_by(PersonErasureMention.id).limit(limit + 1)))
    more = len(found) > limit
    items = found[:limit]
    return row, MentionPage(items, encode_cursor(items[-1].id) if more and items else None)


async def _mention_row(
    session: AsyncSession, erasure_id: uuid.UUID, mention_id: uuid.UUID
) -> PersonErasureMention:
    row = await session.scalar(
        select(PersonErasureMention).where(
            PersonErasureMention.id == mention_id,
            PersonErasureMention.erasure_id == erasure_id,
        )
    )
    if row is None:
        raise NotFound(code=rules.MENTION_NOT_FOUND)
    return row


async def _readable(
    session: AsyncSession, subject: Subject, port: PersonMentions, mention: Mention
) -> str | None:
    """The port's passage, never for a field the subject's field access hides or masks.

    ADR-047 backstop for every port (lane A's #506 review): the port checks the record and its
    own field rules, this checks the role rules by the mention's record type and field name.
    """
    if mention.field in unseen(subject.field_access, mention.record_type):
        return None
    return await port.passage(session, subject, mention)


async def passage(
    session: AsyncSession, subject: Subject, erasure_id: uuid.UUID, mention_id: uuid.UUID
) -> tuple[PersonErasureMention, str]:
    """The mentioned field's current text, when the subject's own rights let them read it.

    404 `erasure_mention_not_found` for a mention of another erasure, of a module with no port,
    or of a record the subject may not read. Only before the job starts.
    """
    erasure = await session.get(PersonErasure, erasure_id)
    if erasure is None:
        raise NotFound(code=rules.NOT_FOUND)
    if not rules.can("redact", ErasureState(erasure.state)).allowed:
        raise Conflict(code=rules.NOT_PENDING, params={"state": erasure.state})
    row = await _mention_row(session, erasure_id, mention_id)
    port = mention_port(row.module_key)
    text = None if port is None else await _readable(session, subject, port, _mention(row))
    if text is None:
        raise NotFound(code=rules.MENTION_NOT_FOUND)
    return row, text


@dataclass(frozen=True)
class Redacted:
    """What a redaction did: the erasure, and each mention newly redacted (and if text changed)."""

    erasure: PersonErasure
    mentions: list[tuple[PersonErasureMention, bool]]


async def redact(  # noqa: PLR0913 - the erasure, its version, who, which mentions, when
    session: AsyncSession,
    subject: Subject,
    erasure_id: uuid.UUID,
    mention_ids: Sequence[uuid.UUID],
    *,
    expected_version: int,
    now: datetime,
) -> Redacted:
    """Replace the chosen mentions' matched text with the D2a marker (before the job starts).

    All or nothing: a mention of another erasure, or of a record the subject's own rights do
    not let them read, refuses the whole request (404): nobody redacts what they cannot see
    (lane B's review of S1b). A mention already redacted is skipped (idempotent).
    """
    actor_id = subject.user_id
    row = await _locked(session, erasure_id, expected_version)
    if not rules.can("redact", ErasureState(row.state)).allowed:
        raise Conflict(code=rules.NOT_PENDING, params={"state": row.state})
    wanted = list(dict.fromkeys(mention_ids))
    found = {
        m.id: m
        for m in await session.scalars(
            select(PersonErasureMention)
            .where(
                PersonErasureMention.erasure_id == erasure_id,
                PersonErasureMention.id.in_(wanted),
            )
            .with_for_update()
        )
    }
    if len(found) != len(wanted):
        raise NotFound(code=rules.MENTION_NOT_FOUND)
    ports = {m.module_key: mention_port(m.module_key) for m in found.values()}
    if any(port is None for port in ports.values()):
        raise Conflict(code=rules.MENTION_PORT_MISSING)
    for mention in found.values():
        port = ports[mention.module_key]
        assert port is not None  # noqa: S101 - checked above; narrows the type
        if await _readable(session, subject, port, _mention(mention)) is None:
            raise NotFound(code=rules.MENTION_NOT_FOUND)
    person = await session.get(User, row.person_id)
    terms = person_terms(person) if person is not None else MentionTerms()
    done: list[tuple[PersonErasureMention, bool]] = []
    for mention_id in wanted:
        mention = found[mention_id]
        if mention.state == MentionState.REDACTED.value:
            continue
        port = ports[mention.module_key]
        assert port is not None  # noqa: S101 - checked above; narrows the type
        changed = await port.redact_mention(
            session, _mention(mention), terms=terms, marker=ERASED_ON_REQUEST, now=now
        )
        mention.state = MentionState.REDACTED.value
        mention.redacted_by, mention.redacted_at = actor_id, now
        mention.version += 1
        await session.flush()
        mention.history_kept = await _redact_history(session, mention.id)
        done.append((mention, changed))
    if done:
        row.version += 1
        await session.flush()
        await _changed(session, row)
    return Redacted(row, done)


# Whether signed history rows can be redacted: False until the audit verifier has a
# `redacted_on_request` status with the field digests kept before blanking (ADR-046 follow-up).
# Until then an erasure that kept such a row is refused at approval and at job start.
SIGNED_HISTORY_REDACTION = False


async def signed_history_kept(session: AsyncSession, erasure_id: uuid.UUID) -> bool:
    """Whether a redacted mention of the erasure left text in signed history (D-171)."""
    if SIGNED_HISTORY_REDACTION:
        return False
    kept = await session.scalar(
        select(func.count())
        .select_from(PersonErasureMention)
        .where(
            PersonErasureMention.erasure_id == erasure_id,
            PersonErasureMention.history_kept > 0,
        )
    )
    return bool(kept)


_REDACT_HISTORY = text("SELECT history_redact_field(:mention) AS result")


async def _redact_history(session: AsyncSession, mention_id: uuid.UUID) -> int:
    """Blank the redacted field's earlier values in record history; the rows kept, by count.

    Through the migrator-owned `history_redact_field()` (0164): it reads the record and field
    from the redacted mention row itself, so no caller can point it at another field.
    """
    result = await session.scalar(_REDACT_HISTORY, {"mention": mention_id})
    return int((result or {}).get("kept_fingerprinted", 0))


def report_summary(row: PersonErasure) -> dict[str, Any] | None:
    """The report as the API shows it (codes and counts only)."""
    report = row.report
    if report is None:
        return None
    return {
        "complete": report_complete(report),
        "building": report.get("building") is not None,
        "by_module": {
            str(module): {str(kind): int(count) for kind, count in kinds.items()}
            for module, kinds in (report.get("by_module") or {}).items()
        },
        "ports_missing": sorted(
            report.get("ports_missing") or missing_mention_ports(set(_done(report)))
        ),
        "attachment_content_searched": ATTACHMENT_CONTENT_SEARCHED,
        "mail_bodies_searched": MAIL_BODIES_SEARCHED,
        "reviewed_at": row.report_reviewed_at,
        "reviewed_by": row.report_reviewed_by,
    }
