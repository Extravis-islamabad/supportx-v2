"""One-off repair (Haider, 2026-11-10; E1): showcase requests fulfilled with nobody on them.

Before D-154's "E1 follows d", a request whose last task was ticked could be fulfilled by
itself with no technician (SR-11 on the shared stack: "Fulfilled", Technician "Not taken
yet"). Since then a request is fulfilled only with someone on it. This gives each such request
of the showcase tenant its fulfiller: a person of its own group (D-154a; the first by name),
or the seed's technician when it has no group.

The showcase tenant only (a guard refuses any other, and production); in its own RLS context
as the migrator, like the dates repair. Each repair is one save: the technician, its
`work_items.work_item.updated` event (so open screens and search follow), a field history
row (source `api`) and one new audit entry, `service_request.fulfiller_repaired`,
sealed into the chain like any other; the audit log is otherwise only read. Dry run by default;
`--apply` writes. A second run finds nothing to repair.

    uv run python -m tooling.repair_showcase_fulfillers showcase            # the plan only
    uv run python -m tooling.repair_showcase_fulfillers showcase --apply    # repair them
"""

import asyncio
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database, create_engine
from app.core.modules import discover_modules
from app.core.tenancy import TenantContext
from app.modules.audit import AuditActorType, RequestFacts
from app.modules.audit import record as record_audit
from app.modules.audit.domain.catalogue import AuditClient
from app.modules.work_items.events import Audience, WorkItemUpdated
from app.shared.events import record_event
from app.shared.history import Change, record_changes
from tooling import showcase_seed as seed

discover_modules()  # every module's tables on the shared metadata (as the seed does)

ACTION = "service_request.fulfiller_repaired"
FACTS = RequestFacts(
    client=AuditClient.WORKER,
    request_id=None,
    ip=None,
    user_agent="supportx-showcase-fulfillers-repair",
)
DONE = ("resolved", "closed")


class RepairError(RuntimeError):
    """The repair must not run (wrong tenant, production, no database)."""


@dataclass
class Plan:
    """One request fulfilled with nobody on it, and who it gets."""

    record_id: uuid.UUID
    display_id: str
    version: int
    fulfiller: uuid.UUID | None
    status: str = ""
    status_category: str = ""
    group_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None

    def line(self) -> str:
        """One line of the dry-run output."""
        who = "nobody to give it (no group member, no seed technician)"
        return f"{self.display_id} ({self.status}): technician -> {self.fulfiller or who}"


def refuse(slug: str, settings: Settings) -> str | None:
    """Why this run must not go ahead, or None (Haider: the showcase tenant only)."""
    if slug != seed.SLUG:
        return f"this repair is only for the tenant {seed.SLUG!r}, never {slug!r}"
    if settings.profile == "production":
        return "refusing to run against production"
    return None


async def _set_tenant(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed.TENANT_ID)}
    )


async def plan(session: AsyncSession) -> list[Plan]:
    """The showcase's fulfilled or closed requests with no technician, each with a fulfiller."""
    await _set_tenant(session)
    technician = await session.scalar(
        text("SELECT id FROM users WHERE tenant_id = :t AND email = :e"),
        {"t": seed.TENANT_ID, "e": seed.TECHNICIAN.email},
    )
    rows = (
        await session.execute(
            text(
                "SELECT id, display_id, version, group_id, site_id, status, status_category"
                " FROM work_items"
                " WHERE tenant_id = :t AND type = 'service_request' AND deleted_at IS NULL"
                # Fulfilled at some point: a rejected one is closed and stamped resolved too,
                # but was never fulfilled; a withdrawn one is canceled.
                " AND technician_id IS NULL AND status_category = ANY(:done)"
                " AND resolved_at IS NOT NULL AND status <> 'rejected'"
                " ORDER BY display_number"
            ),
            {"t": seed.TENANT_ID, "done": list(DONE)},
        )
    ).all()
    plans: list[Plan] = []
    for row in rows:
        fulfiller = technician
        if row.group_id is not None:
            fulfiller = await session.scalar(
                text(
                    "SELECT u.id FROM group_members m JOIN users u ON u.id = m.user_id"
                    " WHERE m.tenant_id = :t AND m.group_id = :g AND u.status = 'active'"
                    " ORDER BY u.display_name, u.id LIMIT 1"
                ),
                {"t": seed.TENANT_ID, "g": row.group_id},
            )
        plans.append(
            Plan(
                row.id,
                row.display_id,
                row.version,
                fulfiller,
                row.status,
                row.status_category,
                row.group_id,
                row.site_id,
            )
        )
    return plans


async def apply(session: AsyncSession, item: Plan) -> uuid.UUID:
    """Give the request its fulfiller, with its history row and audit entry (one save)."""
    if item.fulfiller is None:
        msg = f"{item.display_id} has nobody to give it"
        raise RepairError(msg)
    await _set_tenant(session)
    now = datetime.now(UTC)
    changed = await session.execute(
        text(
            "UPDATE work_items SET technician_id = :p, version = version + 1, updated_at = :now"
            " WHERE tenant_id = :t AND id = :id AND version = :v AND technician_id IS NULL"
        ),
        {
            "p": item.fulfiller,
            "now": now,
            "t": seed.TENANT_ID,
            "id": item.record_id,
            "v": item.version,
        },
    )
    if changed.rowcount != 1:  # type: ignore[attr-defined]  # CursorResult on an UPDATE
        msg = f"{item.display_id} changed since the plan"
        raise RepairError(msg)
    # Open lists, the record and search follow it, as after any save (rule 5b, lane B).
    await record_event(
        session,
        WorkItemUpdated(
            work_item_id=item.record_id,
            type="service_request",
            display_id=item.display_id,
            status=item.status,
            status_category=item.status_category,
            changed_fields=["technician_id"],
            audience_before=Audience(
                group_id=item.group_id, site_id=item.site_id, technician_id=None, unassigned=True
            ),
        ),
        aggregate_id=item.record_id,
        aggregate_version=item.version + 1,
    )
    await record_changes(
        session,
        record_type="work_item",
        record_id=item.record_id,
        version=item.version + 1,
        kind="updated",
        changes=[Change("technician_id", None, str(item.fulfiller))],
        source="api",
    )
    return await record_audit(
        session,
        action_code=ACTION,
        facts=FACTS,
        object_type="service_request",
        object_id=item.record_id,
        actor=(AuditActorType.SYSTEM, None),
        details={
            "display_id": item.display_id,
            "technician_id": str(item.fulfiller),
            "cause": "fulfilled with nobody on it, before D-154 (E1 follows d)",
        },
    )


async def run(settings: Settings, *, write: bool) -> list[Plan]:
    """Plan (read-only), then, with `write`, repair each request in its own transaction."""
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
        async with database.tenant_session(context) as session:
            plans = await plan(session)
            await session.rollback()  # the plan writes nothing
        if write:
            for item in plans:
                if item.fulfiller is None:
                    continue
                async with database.tenant_session(context) as session:
                    await apply(session, item)
    finally:
        await database.dispose()
    return plans


def main(argv: Sequence[str]) -> int:  # pragma: no cover - thin CLI over the tested steps
    """`python -m tooling.repair_showcase_fulfillers showcase [--apply]`."""
    args = [a for a in argv if a != "--apply"]
    write = "--apply" in argv
    settings = Settings.load(service_name="supportx-showcase-repair")
    if len(args) != 1 or (why := refuse(args[0], settings)) is not None:
        print(why if len(args) == 1 else "usage: showcase [--apply]", file=sys.stderr)  # noqa: T201 - CLI
        return 2
    plans = asyncio.run(run(settings, write=write))
    print(f"{'apply' if write else 'dry run'}: {len(plans)} request(s) fulfilled with nobody")  # noqa: T201 - CLI
    for item in plans:
        print("  " + item.line())  # noqa: T201 - CLI
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
