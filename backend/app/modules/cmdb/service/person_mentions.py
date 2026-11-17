"""The CMDB's mentions port for a person's erasure (ADR-052 S1b, D-171 a; 0176).

What people write about a CI is its name and description (plain text). Two record types are
searched, each place with its own mention (lane C's 0176 review):

- `ci`: the CI as it is now, removed ones too (their text is still stored; no passage);
- `ci_version`: each saved snapshot's name and description (`cmdb_ci_versions`), so an old name
  that named the person is found even after the CI was renamed.

Redacting a `ci` mention is an ordinary save of the CI (version, history naming the field only
with reason `erasure_redaction`, a new snapshot, `CiUpdated`); the registry blanks the field's
earlier `field_changes`. Redacting a `ci_version` mention replaces the matched stretches of that
one snapshot field through 0176's migrator-owned `cmdb_redact_version(mention, value)`, which
accepts only the old text with stretches replaced by the marker (the app role may only add
snapshots). Only places that name the person change: an unrelated older name stays. CI custom
text values join with 0175.

The cursor is `<phase>|<last id>`: the CIs first, then the snapshots.
"""

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cmdb.events import CiUpdated
from app.modules.cmdb.infra.models import Ci, CiVersion
from app.modules.cmdb.service.cis import RECORD_TYPE, snapshot, visible_rows
from app.modules.identity_access import (
    MENTION_BATCH,
    Mention,
    MentionBatch,
    MentionTerms,
    Subject,
    count_matches,
    redact_matches,
    register_mentions,
)
from app.shared.events import record_event
from app.shared.history import Change, record_changes
from app.shared.ids import new_id

REDACTION_REASON = "erasure_redaction"  # the history reason code (identity_access's)
VERSION_RECORD_TYPE = "ci_version"
FIELDS = ("name", "description")  # as the CMDB's field catalogue names them (ADR-047)
CIS, VERSIONS = "ci", "ver"  # the cursor's phases
ERASE = "people.erase"  # identity_access's right to erase people (ADR-052)
_REDACT_VERSION = text("SELECT cmdb_redact_version(:mention, :value)")


def _cursor(phase: str, last: uuid.UUID) -> str:
    return f"{phase}|{last}"


def _place(cursor: str | None) -> tuple[str, uuid.UUID | None]:
    if not cursor:
        return CIS, None
    phase, _, last = cursor.partition("|")
    return phase, uuid.UUID(last) if last else None


def _found(
    record_type: str, rid: uuid.UUID, values: dict[str, Any], terms: MentionTerms
) -> list[Mention]:
    return [
        Mention(record_type, rid, field, kind, count)
        for field in FIELDS
        for kind, count in sorted(count_matches(_text(values.get(field)), terms).items())
    ]


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


class CiMentions:
    """CI names and descriptions, now and in every saved snapshot, that name the person."""

    module: ClassVar[str] = "cmdb"

    async def find_mentions(
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        terms: MentionTerms,
        cursor: str | None,
    ) -> MentionBatch:
        """One batch of CIs, then of snapshots, by ID (a CI is never the person's own)."""
        del person_id
        phase, last = _place(cursor)
        if phase == CIS:
            query = select(Ci.id, Ci.name, Ci.description)
            if last is not None:
                query = query.where(Ci.id > last)
            rows = (await session.execute(query.order_by(Ci.id).limit(MENTION_BATCH))).all()
            found = [
                m
                for ci_id, name, description in rows
                for m in _found(
                    RECORD_TYPE, ci_id, {"name": name, "description": description}, terms
                )
            ]
            if len(rows) >= MENTION_BATCH:
                return MentionBatch(tuple(found), _cursor(CIS, rows[-1][0]))
            return MentionBatch(tuple(found), _cursor(VERSIONS, uuid.UUID(int=0)))
        query_v = select(CiVersion.id, CiVersion.snapshot)
        if last is not None:
            query_v = query_v.where(CiVersion.id > last)
        versions = (
            await session.execute(query_v.order_by(CiVersion.id).limit(MENTION_BATCH))
        ).all()
        found = [m for vid, snap in versions for m in _found(VERSION_RECORD_TYPE, vid, snap, terms)]
        more = len(versions) >= MENTION_BATCH
        return MentionBatch(tuple(found), _cursor(VERSIONS, versions[-1][0]) if more else None)

    async def redact_mention(
        self,
        session: AsyncSession,
        mention: Mention,
        *,
        terms: MentionTerms,
        marker: str,
        now: datetime,
    ) -> bool:
        """That kind's occurrences in that one field become the marker; False if none are left."""
        if mention.field not in FIELDS:
            return False
        if mention.record_type == VERSION_RECORD_TYPE:
            return await _redact_version(session, mention, terms, marker)
        if mention.record_type != RECORD_TYPE:
            return False
        # Removed CIs too: the bin keeps their text, so it is redacted like any other.
        row = await session.scalar(select(Ci).where(Ci.id == mention.record_id).with_for_update())
        current = _text(getattr(row, mention.field)) if row is not None else None
        if row is None or not current:
            return False
        redacted, count = redact_matches(current, terms, mention.match_kind, marker)
        if not count:
            return False
        setattr(row, mention.field, redacted)
        row.version, row.updated_at = row.version + 1, now
        await session.flush()
        await _saved(session, row, mention.field)
        return True

    async def passage(
        self, session: AsyncSession, subject: Subject, mention: Mention
    ) -> str | None:
        """The field's text, when the subject may see the CI.

        A CI in the bin (and its snapshots) only for someone who may erase people, as lane B's
        other ports do (0170): the registry redacts only what the redactor can read.
        """
        if mention.field not in FIELDS:
            return None
        if mention.record_type == RECORD_TYPE:
            row = await _seen(session, subject, mention.record_id)
            return (_text(getattr(row, mention.field)) or None) if row is not None else None
        if mention.record_type == VERSION_RECORD_TYPE:
            version = await session.scalar(
                select(CiVersion).where(CiVersion.id == mention.record_id)
            )
            if version is None or await _seen(session, subject, version.ci_id) is None:
                return None
            return _text(version.snapshot.get(mention.field)) or None
        return None


async def _seen(session: AsyncSession, subject: Subject, ci_id: uuid.UUID) -> Ci | None:
    """The CI if the subject may see it: live by their scope; binned only with `people.erase`."""
    row: Ci | None = await session.scalar(visible_rows(subject).where(Ci.id == ci_id))
    if row is None and subject.holds(ERASE):
        row = await session.scalar(visible_rows(subject, trash=True).where(Ci.id == ci_id))
    return row


async def _redact_version(
    session: AsyncSession, mention: Mention, terms: MentionTerms, marker: str
) -> bool:
    """One snapshot field, through the bound definer (0176): stretches only, nothing else."""
    version = await session.scalar(select(CiVersion).where(CiVersion.id == mention.record_id))
    old = _text(version.snapshot.get(mention.field)) if version is not None else None
    if not old:
        return False
    redacted, count = redact_matches(old, terms, mention.match_kind, marker)
    if not count:
        return False
    changed = await session.scalar(
        _REDACT_VERSION, {"mention": mention.mention_id, "value": redacted}
    )
    if changed:
        await session.refresh(version)  # the session's copy matches the row again
    return bool(changed)


async def _saved(session: AsyncSession, row: Ci, field: str) -> None:
    """History naming the field only, the new snapshot and the ordinary event (rule c)."""
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="updated",
        changes=[Change(field, None, None)],
        source="system",
        reason=REDACTION_REASON,
    )
    await session.execute(
        insert(CiVersion).values(
            tenant_id=row.tenant_id,
            id=new_id(),
            ci_id=row.id,
            version=row.version,
            snapshot=snapshot(row),
            saved_by=None,
        )
    )
    await record_event(
        session,
        CiUpdated(ci_id=row.id, type_id=row.type_id, changed_fields=[field]),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


PORT = CiMentions()


def register() -> None:
    """Register the port (the CMDB's import does; idempotent)."""
    register_mentions(PORT)
