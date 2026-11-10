"""One-off repair (QA 2026-11-09, Haider): put back the dates the old seed step 5 moved.

Before #288 the showcase seed's backdating step moved every work item in the tenant except
releases, so records it never made (INC-62, made by hand) were moved into the past 30 days with
their field history. #288 stops that; this script puts those records' times back, from evidence,
and only where the evidence is certain.

Evidence (the audit log has no entry for ordinary incident saves, so it cannot be the source;
the coordinator put this to Haider on 2026-11-09):
- primary: the UUIDv7 time in each row's own primary key (and a history row's change_id). The
  application makes them at insert, and the old step moved timestamp columns only, never ids;
- confirmation: the outbox envelope's `occurred_at` for the record's events while the relay
  still keeps them, and every audit entry linked to the record or its history (read only).

Which records: work items of the showcase tenant whose `created_at` is earlier than their own
id time, which cannot happen without a move, excluding the records the seed itself defines (it
backdates those on purpose: `showcase_seed.is_seed_incident`, and lane A's request and problem
subjects). Releases were never moved.

Certain only (no guessing): a record is repaired when
1. its `created_at` is exactly where the old step put records (the tenant's creation minus the
   step's offset for its display number);
2. one delta, its id time minus its `created_at`, brings every moved row back to its own id
   time (and a history row to its change_id's time), within TOLERANCE;
3. the restored times of the record are not in the future and not before its creation;
4. every outbox event and audit entry still present agrees, within TOLERANCE.
Otherwise it is left as it is and listed "skip: uncertain" with the reason, for Haider.

A row is "moved" when its own time is earlier than the record's id time (impossible otherwise);
rows written since (a later reply, a later history row) are left alone. The repair is exact to
the id's millisecond and the clocks between (about 0.1 s); microseconds are not recoverable.

Each repair runs in its own transaction with `app.tenant_id` set (RLS applies), as the migrator
like the seed's step 5, and appends one audit entry (`work_item.dates_restored`) through the
audit service, sealed into the chain like any other: old and restored value and the evidence.
The audit log itself is only read. Dry run by default; `--apply` writes. A second run finds
nothing to repair (the restored records match their id times) and writes nothing.

    uv run python -m tooling.repair_showcase_dates showcase            # the plan only
    uv run python -m tooling.repair_showcase_dates showcase --apply    # repair the certain ones
"""

import asyncio
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database, create_engine
from app.core.modules import discover_modules
from app.core.tenancy import TenantContext
from app.modules.audit import AuditActorType, RequestFacts
from app.modules.audit import record as record_audit
from app.modules.audit.domain.catalogue import AuditClient
from app.shared.ids import id_created_at
from tooling import showcase_lane_a as lane_a
from tooling import showcase_seed as seed

discover_modules()  # every module's tables on the shared metadata (as the seed does)

TOLERANCE = timedelta(seconds=2)
ACTION = "work_item.dates_restored"
FACTS = RequestFacts(
    client=AuditClient.WORKER,
    request_id=None,
    ip=None,
    user_agent="supportx-showcase-dates-repair",
)
# The record's own times that must make sense once restored (not in the future, not before it).
EVENT_COLUMNS = ("created_at", "updated_at", "first_responded_at", "resolved_at", "closed_at")
_RECORD_TIMES = f"SELECT {', '.join(EVENT_COLUMNS)} FROM work_items WHERE id = :id"  # noqa: S608 - fixed names
UUID_V7 = 7


class RepairError(RuntimeError):
    """The repair must not run (wrong tenant, production, no database)."""


@dataclass
class Plan:
    """What the repair would do (or why not) for one record."""

    record_id: uuid.UUID
    display_id: str
    record_type: str
    current: datetime
    restored: datetime | None = None
    delta: timedelta | None = None
    evidence: list[str] = field(default_factory=list)
    skip: str | None = None
    # table -> how many rows move back
    rows: dict[str, int] = field(default_factory=dict)
    # For the dry run: each column and history save, current -> restored (and its evidence).
    details: list[str] = field(default_factory=list)

    def line(self) -> str:
        """One line of the dry-run output."""
        if self.skip is not None:
            return f"{self.display_id}: skip: uncertain ({self.skip}); created_at {self.current}"
        rows = ", ".join(f"{t} {n}" for t, n in self.rows.items() if n)
        return (
            f"{self.display_id}: created_at {self.current} -> {self.restored}"
            f" (delta {self.delta}); rows: {rows}; evidence: {'; '.join(self.evidence)}"
            + "".join(f"\n      {d}" for d in self.details)
        )


def refuse(slug: str, settings: Settings) -> str | None:
    """Why this run must not go ahead, or None (Haider: the showcase tenant only)."""
    if slug != seed.SLUG:
        return f"this repair is only for the tenant {seed.SLUG!r}, never {slug!r}"
    if settings.profile == "production":
        return "refusing to run against production"
    return None


def _close(a: datetime, b: datetime) -> bool:
    return abs(a - b) <= TOLERANCE


async def _set_tenant(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed.TENANT_ID)}
    )


async def _check_role(session: AsyncSession) -> None:
    """Refuse to start unless RLS confines this role (Haider, 2026-11-09).

    The role must not be a superuser and must not have BYPASSRLS, and every table the repair
    reads or writes must force RLS, so the database keeps it inside the showcase tenant even if
    a guard here had a bug (read-only queries run as postgres once crossed tenants silently).
    """
    role = (
        await session.execute(
            text(
                "SELECT current_user AS name, rolsuper, rolbypassrls FROM pg_roles"
                " WHERE rolname = current_user"
            )
        )
    ).one()
    if role.rolsuper or role.rolbypassrls:
        msg = (
            f"refusing to run as {role.name}: a superuser or BYPASSRLS role is not confined by RLS"
        )
        raise RepairError(msg)
    tables = [t for t, _ in seed._BACKDATE_TARGETS] + ["audit_entries", "outbox_events"]  # noqa: SLF001 - step 5's tables
    loose = (
        (
            await session.execute(
                text(
                    "SELECT relname FROM pg_class WHERE relname = ANY(:t) AND relkind IN ('r', 'p')"
                    " AND NOT (relrowsecurity AND relforcerowsecurity) ORDER BY relname"
                ),
                {"t": tables},
            )
        )
        .scalars()
        .all()
    )
    if loose:
        msg = f"refusing to run: RLS is not forced on {', '.join(loose)}"
        raise RepairError(msg)


async def _check_tenant(session: AsyncSession) -> None:
    found = await session.scalar(
        text("SELECT id FROM tenants WHERE slug = :slug"), {"slug": seed.SLUG}
    )
    if found != seed.TENANT_ID:
        msg = f"the slug {seed.SLUG!r} is not the showcase tenant {seed.TENANT_ID}; nothing done"
        raise RepairError(msg)


async def _columns(session: AsyncSession, table: str) -> tuple[list[str], bool]:
    """The table's timestamp columns, and whether it has a UUID `id`."""
    rows = (
        await session.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns"
                " WHERE table_schema = 'public' AND table_name = :t ORDER BY column_name"
            ),
            {"t": table},
        )
    ).all()
    stamps = [r.column_name for r in rows if r.data_type == "timestamp with time zone"]
    has_id = any(r.column_name == "id" and r.data_type == "uuid" for r in rows)
    return stamps, has_id


def _time_column(stamps: Sequence[str]) -> str | None:
    """The column that says when a row was written."""
    for name in ("created_at", "occurred_at", "entered_at"):
        if name in stamps:
            return name
    return None


async def _seed_defined(session: AsyncSession) -> Any:  # noqa: ANN401 - a predicate
    """A test for the records the seed defines (they are backdated on purpose)."""
    emails = [p.email for p in seed.PEOPLE]
    rows = (
        await session.execute(
            text("SELECT email, id FROM users WHERE email = ANY(:e)"), {"e": emails}
        )
    ).all()
    people = {r.email: str(r.id) for r in rows}
    requests = {
        subject for subject, *_ in (*lane_a.REQUESTS, *lane_a.LOCAL_REQUESTS)
    } | lane_a.FIRST_SUBJECTS
    problems = {p[0] for p in lane_a.PROBLEMS}

    def defined(kind: str, subject: str, requester: str | None) -> bool:
        if kind == "incident":
            return len(people) == len(emails) and seed.is_seed_incident(
                {"subject": subject, "requester_id": requester}, people
            )
        if kind == "service_request":
            return subject in requests
        if kind == "problem":
            return subject in problems
        return True  # releases (never moved) and anything else: not this repair's

    return defined


async def plan(session: AsyncSession, now: datetime) -> list[Plan]:
    """Every moved record not the seed's, with its repair or why it is skipped. Reads only."""
    await _check_role(session)
    await _set_tenant(session)
    await _check_tenant(session)
    defined = await _seed_defined(session)
    records = (
        await session.execute(
            text(
                "SELECT w.id, w.type, w.display_id, w.display_number, w.subject,"
                " w.requester_id, t.created_at AS tenant_created,"
                " (t.created_at - make_interval("
                "   days => 1 + ((w.display_number * 7) % :days)::int,"
                "   hours => ((w.display_number * 5) % 9)::int)) AS old_target"
                " FROM work_items w JOIN tenants t ON t.id = w.tenant_id"
                " WHERE w.tenant_id = :tenant ORDER BY w.display_id"
            ),
            {"tenant": seed.TENANT_ID, "days": seed.BACKDATE_DAYS},
        )
    ).all()
    plans: list[Plan] = []
    for r in records:
        row = (
            (
                await session.execute(
                    text(_RECORD_TIMES),
                    {"id": r.id},
                )
            )
            .mappings()
            .one()
        )
        born = id_created_at(r.id)
        if row["created_at"] >= born - TOLERANCE:
            continue  # never moved (or already repaired)
        requester = None if r.requester_id is None else str(r.requester_id)
        if defined(r.type, r.subject, requester):
            continue  # the seed's own record, backdated on purpose
        item = Plan(r.id, r.display_id, r.type, row["created_at"])
        plans.append(item)
        await _judge(session, item, row=dict(row), born=born, old_target=r.old_target, now=now)
    return plans


async def _judge(  # noqa: C901, PLR0912, PLR0913 - one check per kind of evidence, flat
    session: AsyncSession,
    item: Plan,
    *,
    row: Mapping[str, Any],
    born: datetime,
    old_target: datetime,
    now: datetime,
) -> None:
    """Fill in the repair, or the reason it is uncertain."""
    if row["created_at"] != old_target:
        item.skip = "created_at is not where the old step put records"
        return
    delta = born - row["created_at"]
    item.delta, item.restored = delta, born
    item.evidence.append(f"id time {born.isoformat()}")
    for column in EVENT_COLUMNS:
        value = row[column]
        if value is None:
            continue
        back = value + delta
        item.details.append(f"work_items.{column}: {value.isoformat()} -> {back.isoformat()}")
        if back > now + TOLERANCE or back < born - TOLERANCE:
            item.skip = f"{column} would be {back.isoformat()} (not moved with the record?)"
            return
    for table, link in seed._BACKDATE_TARGETS:  # noqa: SLF001 - the very tables step 5 moved
        if table == "work_items":
            continue
        stamps, has_id = await _columns(session, table)
        when = _time_column(stamps)
        if when is None:
            continue
        found = (
            await session.execute(
                text(
                    f"SELECT {'t.id' if has_id else 'NULL'} AS id, t.{when} AS at"  # noqa: S608 - names from the fixed list and the catalogue
                    + (", t.change_id" if table == "field_changes" else "")
                    + f" FROM {table} t, (SELECT CAST(:id AS uuid) AS id) s"
                    f" WHERE t.tenant_id = :tenant AND {link} AND t.{when} < :born"
                ),
                {"id": item.record_id, "tenant": seed.TENANT_ID, "born": born - TOLERANCE},
            )
        ).all()
        for moved in found:
            back = moved.at + delta
            if back > now + TOLERANCE:
                item.skip = f"a {table} row would be in the future"
                return
            if (
                moved.id is not None
                and moved.id.version == UUID_V7
                and not _close(back, id_created_at(moved.id))
            ):
                item.skip = f"a {table} row ({moved.id}) does not come back to its id time"
                return
            change = getattr(moved, "change_id", None)
            if change is not None and not _close(back, id_created_at(change)):
                item.skip = f"a history row ({moved.id}) does not match its change_id time"
                return
        item.rows[table] = len(found)
        groups: dict[Any, list[Any]] = {}
        for moved in found:
            key = getattr(moved, "change_id", None) or moved.id
            groups.setdefault(key, []).append(moved)
        for key, members in groups.items():
            first = members[0]
            proof = id_created_at(key) if isinstance(key, uuid.UUID) else None
            item.details.append(
                f"{table} x{len(members)}: {first.at.isoformat()}"
                f" -> {(first.at + delta).isoformat()}"
                + ("" if proof is None else f" (id time {proof.isoformat()})")
            )
    item.rows = {"work_items": 1, **item.rows}
    await _confirm(session, item, delta)


async def _confirm(session: AsyncSession, item: Plan, delta: timedelta) -> None:
    """The outbox events still kept and any linked audit entries must agree (read only)."""
    created = (
        await session.execute(
            text(
                "SELECT id, envelope->>'occurred_at' AS at FROM outbox_events"
                " WHERE aggregate_id = :id AND event_type LIKE '%.created' ORDER BY id"
            ),
            {"id": str(item.record_id)},
        )
    ).all()
    if len(created) > 1:
        item.skip = "more than one created event in the outbox"
        return
    if created:
        at = datetime.fromisoformat(created[0].at)
        if item.restored is None or not _close(at, item.restored):
            item.skip = f"the outbox created event ({created[0].id}) says {at.isoformat()}"
            return
        item.evidence.append(f"outbox event {created[0].id} at {at.isoformat()}")
    else:
        item.evidence.append("outbox: no created event kept")
    audits = (
        await session.execute(
            text(
                "SELECT a.id, a.occurred_at, a.change_id FROM audit_entries a"
                " WHERE a.tenant_id = :tenant AND a.action <> :action AND (a.object_id = :rid"
                "  OR a.change_id IN (SELECT f.change_id FROM field_changes f"
                "   WHERE f.record_type = 'work_item' AND f.record_id = CAST(:rid AS uuid)))"
            ),
            {"tenant": seed.TENANT_ID, "action": ACTION, "rid": str(item.record_id)},
        )
    ).all()
    for entry in audits:
        if entry.change_id is None:
            continue
        times = (
            await session.execute(
                text(
                    "SELECT occurred_at FROM field_changes"
                    " WHERE change_id = :c AND record_id = CAST(:rid AS uuid)"
                ),
                {"c": entry.change_id, "rid": str(item.record_id)},
            )
        ).scalars()
        if not any(_close(t + delta, entry.occurred_at) for t in times):
            item.skip = f"audit entry {entry.id} disagrees with its history row"
            return
    item.evidence.append(f"audit entries checked: {len(audits)}")


async def apply(session: AsyncSession, item: Plan) -> uuid.UUID:
    """Move the record's moved rows back by its delta and audit it; in the caller's transaction."""
    if item.skip is not None or item.delta is None or item.restored is None:
        msg = f"{item.display_id} is not a certain repair"
        raise RepairError(msg)
    await _set_tenant(session)
    born = item.restored
    for table, link in seed._BACKDATE_TARGETS:  # noqa: SLF001 - the very tables step 5 moved
        stamps, _ = await _columns(session, table)
        when = _time_column(stamps)
        if when is None:
            continue
        shift = ", ".join(f"{c} = t.{c} + :delta" for c in stamps)
        await session.execute(
            text(
                f"UPDATE {table} t SET {shift} FROM (SELECT CAST(:id AS uuid) AS id) s"  # noqa: S608 - names from the fixed list and the catalogue
                f" WHERE t.tenant_id = :tenant AND {link} AND t.{when} < :born"
            ),
            {
                "delta": item.delta,
                "id": item.record_id,
                "tenant": seed.TENANT_ID,
                "born": born - TOLERANCE,
            },
        )
    return await record_audit(
        session,
        action_code=ACTION,
        facts=FACTS,
        object_type=item.record_type,
        object_id=item.record_id,
        actor=(AuditActorType.SYSTEM, None),
        details={
            "display_id": item.display_id,
            "created_at_was": item.current.isoformat(),
            "created_at_restored": item.restored.isoformat(),
            "delta_ms": int(item.delta / timedelta(milliseconds=1)),
            "rows_restored": {t: n for t, n in item.rows.items() if n},
            "evidence": item.evidence,
            "cause": "showcase seed step 5 before #288",
        },
    )


async def run(settings: Settings, *, write: bool) -> list[Plan]:
    """Plan (read-only), then, with `write`, repair each certain record in its own transaction."""
    url = settings.migration_database_url
    if url is None:
        msg = "SUPPORTX_MIGRATION_DATABASE_URL must be set"
        raise RepairError(msg)
    database = Database(
        create_engine(
            url.get_secret_value(), application_name="showcase-repair", use_null_pool=True
        )
    )
    context = TenantContext(seed.TENANT_ID)
    try:
        now = datetime.now(UTC)
        async with database.tenant_session(context) as session:
            plans = await plan(session, now)
            await session.rollback()  # the plan writes nothing
        if write:
            for item in plans:
                if item.skip is not None:
                    continue
                async with database.tenant_session(context) as session:
                    # Judged again inside its own transaction: nothing changed in between.
                    fresh = [p for p in await plan(session, now) if p.record_id == item.record_id]
                    if not fresh or fresh[0].skip is not None:
                        item.skip = "changed since the plan"
                        continue
                    item.evidence.append(f"audit {await apply(session, fresh[0])}")
    finally:
        await database.dispose()
    return plans


def main(argv: Sequence[str]) -> int:  # pragma: no cover - thin CLI over the tested steps
    """`python -m tooling.repair_showcase_dates showcase [--apply]`."""
    args = [a for a in argv if a != "--apply"]
    write = "--apply" in argv
    settings = Settings.load(service_name="supportx-showcase-repair")
    if len(args) != 1 or (why := refuse(args[0], settings)) is not None:
        print(why if len(args) == 1 else "usage: showcase [--apply]", file=sys.stderr)  # noqa: T201 - CLI
        return 2
    plans = asyncio.run(run(settings, write=write))
    print(f"{'apply' if write else 'dry run'}: {len(plans)} moved record(s) not the seed's")  # noqa: T201 - CLI
    for item in plans:
        print("  " + item.line())  # noqa: T201 - CLI
    certain = sum(p.skip is None for p in plans)
    print(f"certain: {certain}; uncertain (left as they are): {len(plans) - certain}")  # noqa: T201 - CLI
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
