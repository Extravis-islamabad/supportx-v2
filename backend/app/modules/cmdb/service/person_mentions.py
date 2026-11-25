"""The CMDB's mentions port for a person's erasure (ADR-052 S1b, D-171 a; 0176).

What people write about a CI is its name and description (plain text). Two record types are
searched, each place with its own mention (lane C's 0176 review):

- `ci`: the CI as it is now, removed ones too (their text is still stored; no passage);
- `ci_version`: each saved snapshot's name and description (`cmdb_ci_versions`), so an old name
  that named the person is found even after the CI was renamed;
- `ci_business_view` (S2, 0180): a business view's name and description, removed views too.

Redacting a `ci` mention is an ordinary save of the CI (version, history naming the field only
with reason `erasure_redaction`, a new snapshot, `CiUpdated`); the registry blanks the field's
earlier `field_changes`. Redacting a `ci_version` mention replaces the matched stretches of that
one snapshot field through 0176's migrator-owned `cmdb_redact_version(mention, value)`, which
accepts only the old text with stretches replaced by the marker (the app role may only add
snapshots). Only places that name the person change: an unrelated older name stays.

CI custom values (0175 part 2) that are text a person typed (text, long text, email, phone and
link fields, and any value of a field removed since) are mentions too, as field `custom.<key>`:
on the CI now, an ordinary save of that one key; in a saved snapshot, through 0181's
migrator-owned `cmdb_redact_version_custom(mention, value)`, which takes the key from the bound
mention and accepts only the old text with stretches replaced by the marker (as 0176).

- `ci_baseline` (S7b, 0209): a baseline's own name; `ci_baseline_snapshot`: the name,
  description and typed custom text of the CI copy it holds. Deleted baselines too.

Redacting a `ci_business_view` mention is an ordinary save of the view (version, history naming
the field only with reason `erasure_redaction`, `cmdb.business_view.changed`): views are editable
rows, so no definer is needed.

Redacting a baseline mention is an update of that one baseline (its version, history naming the
field only with reason `erasure_redaction`, `cmdb.baseline.changed` with action `redacted`):
baselines are app-updatable rows, so no definer is needed.

The cursor is `<phase>|<last id>`: the CIs first, then the snapshots, then the business views,
then the baselines.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import metadata
from app.modules.cmdb.domain import field_access as field_rules
from app.modules.cmdb.events import BaselineChanged, BusinessViewChanged, CiUpdated
from app.modules.cmdb.infra.models import BusinessView, Ci, CiBaseline, CiVersion
from app.modules.cmdb.service.business_views import RECORD_TYPE as VIEW_RECORD_TYPE
from app.modules.cmdb.service.business_views import visible_views
from app.modules.cmdb.service.cis import RECORD_TYPE, snapshot, visible_rows
from app.modules.cmdb.service.snapshots import save_version
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

REDACTION_REASON = "erasure_redaction"  # the history reason code (identity_access's)
VERSION_RECORD_TYPE = "ci_version"
FIELDS = ("name", "description")  # as the CMDB's field catalogue names them (ADR-047)
# Custom field types whose values are text someone typed (choices are codes, people are IDs).
TEXT_TYPES = frozenset(
    {
        metadata.FieldType.TEXT,
        metadata.FieldType.LONG_TEXT,
        metadata.FieldType.EMAIL,
        metadata.FieldType.PHONE,
        metadata.FieldType.URL,
    }
)
BASELINE_RECORD_TYPE = "ci_baseline"  # a baseline's own name (S7b)
BASELINE_COPY_RECORD_TYPE = "ci_baseline_snapshot"  # the CI copy a baseline holds (S7b)
CIS, VERSIONS, VIEWS, BASES = "ci", "ver", "view", "base"  # the cursor's phases
ERASE = "people.erase"  # identity_access's right to erase people (ADR-052)
_REDACT_VERSION = text("SELECT cmdb_redact_version(:mention, :value)")
_REDACT_VERSION_CUSTOM = text("SELECT cmdb_redact_version_custom(:mention, :value)")


def _cursor(phase: str, last: uuid.UUID) -> str:
    return f"{phase}|{last}"


def _place(cursor: str | None) -> tuple[str, uuid.UUID | None]:
    if not cursor:
        return CIS, None
    phase, _, last = cursor.partition("|")
    return phase, uuid.UUID(last) if last else None


def _found(
    record_type: str,
    rid: uuid.UUID,
    values: dict[str, Any],
    terms: MentionTerms,
    custom_text: "_CustomText | None" = None,
) -> list[Mention]:
    places = [(field, values.get(field)) for field in FIELDS]
    if custom_text is not None:
        places += custom_text.places(values.get("custom"))
    return [
        Mention(record_type, rid, field, kind, count)
        for field, value in places
        for kind, count in sorted(count_matches(_text(value), terms).items())
    ]


class _CustomText:
    """Which CI custom keys hold typed text: text-like fields, and fields removed since.

    A key no live field has (removed while in use) is read as text: its old value may name the
    person, and only text-like values ever match a person's name or email anyway.
    """

    def __init__(self, definitions: Mapping[str, metadata.Definition]) -> None:
        self._other = frozenset(k for k, d in definitions.items() if d.type not in TEXT_TYPES)

    def is_text(self, key: str) -> bool:
        return key not in self._other

    def places(self, custom: object) -> list[tuple[str, object]]:
        if not isinstance(custom, dict):
            return []
        return [
            (f"{field_rules.CUSTOM}{k}", v)
            for k, v in sorted(custom.items())
            if isinstance(v, str) and self.is_text(k)
        ]


async def _custom_text(session: AsyncSession) -> _CustomText:
    return _CustomText(await metadata.definitions(session, metadata.CustomFieldEntity.CI))


def _custom_key(field: str) -> str | None:
    """The custom key of a mention's field, or None when it is not a custom one."""
    key = field.removeprefix(field_rules.CUSTOM)
    return key if key != field and key else None


def _known(field: str) -> bool:
    return field in FIELDS or _custom_key(field) is not None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


class CiMentions:
    """CI names and descriptions, now and in every saved snapshot, that name the person."""

    module: ClassVar[str] = "cmdb"

    async def find_mentions(  # noqa: PLR0911 - one early answer per phase, flat
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
        texts = await _custom_text(session) if phase in {CIS, VERSIONS, BASES} else None
        if phase == CIS:
            query = select(Ci.id, Ci.name, Ci.description, Ci.custom)
            if last is not None:
                query = query.where(Ci.id > last)
            rows = (await session.execute(query.order_by(Ci.id).limit(MENTION_BATCH))).all()
            found = [
                m
                for ci_id, name, description, custom in rows
                for m in _found(
                    RECORD_TYPE,
                    ci_id,
                    {"name": name, "description": description, "custom": custom},
                    terms,
                    texts,
                )
            ]
            if len(rows) >= MENTION_BATCH:
                return MentionBatch(tuple(found), _cursor(CIS, rows[-1][0]))
            return MentionBatch(tuple(found), _cursor(VERSIONS, uuid.UUID(int=0)))
        if phase == VERSIONS:
            query_v = select(CiVersion.id, CiVersion.snapshot)
            if last is not None:
                query_v = query_v.where(CiVersion.id > last)
            versions = (
                await session.execute(query_v.order_by(CiVersion.id).limit(MENTION_BATCH))
            ).all()
            found = [
                m
                for vid, snap in versions
                for m in _found(VERSION_RECORD_TYPE, vid, snap, terms, texts)
            ]
            if len(versions) >= MENTION_BATCH:
                return MentionBatch(tuple(found), _cursor(VERSIONS, versions[-1][0]))
            return MentionBatch(tuple(found), _cursor(VIEWS, uuid.UUID(int=0)))
        if phase == BASES:
            return await _baseline_mentions(session, last, terms, texts)
        query_w = select(BusinessView.id, BusinessView.name, BusinessView.description)
        if last is not None:
            query_w = query_w.where(BusinessView.id > last)
        views = (
            await session.execute(query_w.order_by(BusinessView.id).limit(MENTION_BATCH))
        ).all()
        found = [
            m
            for vid, name, description in views
            for m in _found(
                VIEW_RECORD_TYPE, vid, {"name": name, "description": description}, terms
            )
        ]
        if len(views) >= MENTION_BATCH:
            return MentionBatch(tuple(found), _cursor(VIEWS, views[-1][0]))
        return MentionBatch(tuple(found), _cursor(BASES, uuid.UUID(int=0)))

    async def redact_mention(  # noqa: PLR0911 - one early answer per place, flat
        self,
        session: AsyncSession,
        mention: Mention,
        *,
        terms: MentionTerms,
        marker: str,
        now: datetime,
    ) -> bool:
        """That kind's occurrences in that one field become the marker; False if none are left."""
        if not _known(mention.field):
            return False
        if mention.record_type == VERSION_RECORD_TYPE:
            return await _redact_version(session, mention, terms, marker)
        if mention.record_type == RECORD_TYPE and (key := _custom_key(mention.field)):
            return await _redact_ci_custom(
                session, mention, key, terms=terms, marker=marker, now=now
            )
        if mention.record_type == VIEW_RECORD_TYPE:
            return await _redact_view(session, mention, terms, marker, now)
        if mention.record_type in {BASELINE_RECORD_TYPE, BASELINE_COPY_RECORD_TYPE}:
            return await _redact_baseline(session, mention, terms, marker, now)
        if mention.record_type == RECORD_TYPE:
            return await _redact_ci(session, mention, terms, marker, now)
        return False

    async def passage(  # noqa: PLR0911 - one early answer per place, flat
        self, session: AsyncSession, subject: Subject, mention: Mention
    ) -> str | None:
        """The field's text, when the subject may see the CI.

        A CI in the bin (and its snapshots) only for someone who may erase people, as lane B's
        other ports do (0170): the registry redacts only what the redactor can read.
        """
        if not _known(mention.field):
            return None
        key = _custom_key(mention.field)
        if (
            key is not None
            and mention.field in field_rules.unseen(subject.field_access, RECORD_TYPE).all
        ):
            return None  # a custom field the subject's roles withhold (ADR-047)
        if mention.record_type == RECORD_TYPE:
            row = await _seen(session, subject, mention.record_id)
            if row is None:
                return None
            value = (row.custom or {}).get(key) if key else getattr(row, mention.field)
            return _text(value) or None
        if mention.record_type == VERSION_RECORD_TYPE:
            version = await session.scalar(
                select(CiVersion).where(CiVersion.id == mention.record_id)
            )
            if version is None or await _seen(session, subject, version.ci_id) is None:
                return None
            held = version.snapshot.get("custom") if key else None
            value = held.get(key) if isinstance(held, dict) else version.snapshot.get(mention.field)
            return _text(value) or None
        if mention.record_type in {BASELINE_RECORD_TYPE, BASELINE_COPY_RECORD_TYPE}:
            baseline = await _seen_baseline(session, subject, mention.record_id)
            if baseline is None:
                return None
            return _text(_baseline_value(baseline, mention)) or None
        if mention.record_type == VIEW_RECORD_TYPE:
            view = await _seen_view(session, subject, mention.record_id)
            return (_text(getattr(view, mention.field)) or None) if view is not None else None
        return None


async def _seen(session: AsyncSession, subject: Subject, ci_id: uuid.UUID) -> Ci | None:
    """The CI if the subject may see it: live by their scope; binned only with `people.erase`."""
    row: Ci | None = await session.scalar(visible_rows(subject).where(Ci.id == ci_id))
    if row is None and subject.holds(ERASE):
        row = await session.scalar(visible_rows(subject, trash=True).where(Ci.id == ci_id))
    return row


async def _redact_ci(
    session: AsyncSession, mention: Mention, terms: MentionTerms, marker: str, now: datetime
) -> bool:
    """One CI field: an ordinary save (removed CIs too: the bin keeps their text)."""
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


async def _redact_ci_custom(  # noqa: PLR0913 - the mention, its key and the redaction's parts
    session: AsyncSession,
    mention: Mention,
    key: str,
    *,
    terms: MentionTerms,
    marker: str,
    now: datetime,
) -> bool:
    """One CI custom value: an ordinary save of that one key (removed CIs too)."""
    row = await session.scalar(select(Ci).where(Ci.id == mention.record_id).with_for_update())
    current = _text((row.custom or {}).get(key)) if row is not None else None
    if row is None or not current:
        return False
    redacted, count = redact_matches(current, terms, mention.match_kind, marker)
    if not count:
        return False
    row.custom = {**(row.custom or {}), key: redacted}
    row.version, row.updated_at = row.version + 1, now
    await session.flush()
    await _saved(session, row, mention.field)
    return True


async def _seen_view(
    session: AsyncSession, subject: Subject, view_id: uuid.UUID
) -> BusinessView | None:
    """The view if the subject may see it (its base CI); a removed one only with `people.erase`."""
    row: BusinessView | None = await session.scalar(
        visible_views(subject).where(BusinessView.id == view_id)
    )
    if row is None and subject.holds(ERASE):
        removed = await session.scalar(
            select(BusinessView).where(
                BusinessView.id == view_id, BusinessView.deleted_at.is_not(None)
            )
        )
        if removed is not None and await _seen(session, subject, removed.base_ci_id) is not None:
            row = removed
    return row


async def _redact_view(
    session: AsyncSession, mention: Mention, terms: MentionTerms, marker: str, now: datetime
) -> bool:
    """One view field: an ordinary save (removed views too: their text is still stored)."""
    row = await session.scalar(
        select(BusinessView).where(BusinessView.id == mention.record_id).with_for_update()
    )
    current = _text(getattr(row, mention.field)) if row is not None else None
    if row is None or not current:
        return False
    redacted, count = redact_matches(current, terms, mention.match_kind, marker)
    if not count:
        return False
    setattr(row, mention.field, redacted)
    row.version, row.updated_at = row.version + 1, now
    await session.flush()
    await record_changes(
        session,
        record_type=VIEW_RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="updated",
        changes=[Change(mention.field, None, None)],
        source="system",
        reason=REDACTION_REASON,
    )
    await record_event(
        session,
        BusinessViewChanged(
            view_id=row.id,
            base_ci_id=row.base_ci_id,
            action="updated",
            changed_fields=[mention.field],
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return True


async def _redact_version(
    session: AsyncSession, mention: Mention, terms: MentionTerms, marker: str
) -> bool:
    """One snapshot field through its bound definer: stretches only, nothing else.

    Name and description go through 0176's `cmdb_redact_version`, a custom value through 0181's
    `cmdb_redact_version_custom`.
    """
    version = await session.scalar(select(CiVersion).where(CiVersion.id == mention.record_id))
    if version is None:
        return False
    key = _custom_key(mention.field)
    if key is None:
        old, call = _text(version.snapshot.get(mention.field)), _REDACT_VERSION
    else:
        held = version.snapshot.get("custom")
        old = _text(held.get(key)) if isinstance(held, dict) else None
        call = _REDACT_VERSION_CUSTOM
    if not old:
        return False
    redacted, count = redact_matches(old, terms, mention.match_kind, marker)
    if not count:
        return False
    changed = await session.scalar(call, {"mention": mention.mention_id, "value": redacted})
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
    await save_version(session, row, snapshot(row), None)
    await record_event(
        session,
        CiUpdated(ci_id=row.id, type_id=row.type_id, changed_fields=[field]),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def _baseline_mentions(
    session: AsyncSession,
    last: uuid.UUID | None,
    terms: MentionTerms,
    texts: "_CustomText | None",
) -> MentionBatch:
    """One batch of baselines (deleted ones too): their own name, then the copy they hold."""
    query = select(CiBaseline.id, CiBaseline.name, CiBaseline.snapshot)
    if last is not None:
        query = query.where(CiBaseline.id > last)
    rows = (await session.execute(query.order_by(CiBaseline.id).limit(MENTION_BATCH))).all()
    found = [
        m
        for bid, name, snap in rows
        for m in (
            *[
                Mention(BASELINE_RECORD_TYPE, bid, "name", kind, count)
                for kind, count in sorted(count_matches(_text(name), terms).items())
            ],
            *_found(BASELINE_COPY_RECORD_TYPE, bid, snap, terms, texts),
        )
    ]
    more = len(rows) >= MENTION_BATCH
    return MentionBatch(tuple(found), _cursor(BASES, rows[-1][0]) if more else None)


def _baseline_value(row: CiBaseline, mention: Mention) -> object:
    """The mentioned text: the baseline's name, or a field of its copy."""
    if mention.record_type == BASELINE_RECORD_TYPE:
        return row.name if mention.field == "name" else None
    if key := _custom_key(mention.field):
        held = row.snapshot.get("custom")
        return held.get(key) if isinstance(held, dict) else None
    return row.snapshot.get(mention.field)


async def _seen_baseline(
    session: AsyncSession, subject: Subject, baseline_id: uuid.UUID
) -> CiBaseline | None:
    """The baseline if the subject may see its CI; a deleted one only with `people.erase`."""
    row: CiBaseline | None = await session.scalar(
        select(CiBaseline).where(CiBaseline.id == baseline_id)
    )
    if row is None or (row.deleted_at is not None and not subject.holds(ERASE)):
        return None
    return row if await _seen(session, subject, row.ci_id) is not None else None


async def _redact_baseline(
    session: AsyncSession, mention: Mention, terms: MentionTerms, marker: str, now: datetime
) -> bool:
    """One baseline field (its name, or a field of its copy): an update of that baseline."""
    row = await session.scalar(
        select(CiBaseline).where(CiBaseline.id == mention.record_id).with_for_update()
    )
    current = _text(_baseline_value(row, mention)) if row is not None else None
    if row is None or not current:
        return False
    redacted, count = redact_matches(current, terms, mention.match_kind, marker)
    if not count:
        return False
    if mention.record_type == BASELINE_RECORD_TYPE:
        row.name = redacted
    elif key := _custom_key(mention.field):
        held = row.snapshot.get("custom")
        row.snapshot = {**row.snapshot, "custom": {**(held or {}), key: redacted}}
    else:
        row.snapshot = {**row.snapshot, mention.field: redacted}
    row.version, row.updated_at = row.version + 1, now
    await session.flush()
    field = (
        mention.field
        if mention.record_type == BASELINE_RECORD_TYPE
        else f"snapshot.{mention.field}"
    )
    await record_changes(
        session,
        record_type=BASELINE_RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="updated",
        changes=[Change(field, None, None)],
        source="system",
        reason=REDACTION_REASON,
    )
    await record_event(
        session,
        BaselineChanged(baseline_id=row.id, ci_id=row.ci_id, action="redacted"),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return True


PORT = CiMentions()


def register() -> None:
    """Register the port (the CMDB's import does; idempotent)."""
    register_mentions(PORT)
