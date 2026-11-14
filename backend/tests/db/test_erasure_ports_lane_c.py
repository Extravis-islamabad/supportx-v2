"""Lane C's erasure ports on real Postgres (ADR-052 S2; knowledge, analytics, announcements, ai).

Each port, run to the end for tech_b with tech_a as the successor:
- deletes what is theirs (votes, favourites, preferences, exports, private dashboards, follows,
  dismissals, AI calls), and their never-submitted drafts are blanked and soft-deleted;
- moves what is shared to the successor (topics, articles, shared dashboards, reports, folders,
  announcements); scheduled reports move PAUSED (`owner_changed`), and tech_b leaves others'
  recipient lists;
- leaves tech_a's rows and the other tenant's rows alone;
- a second run changes nothing (zero counts);
- writes each moved object's ordinary event to the outbox (rule c).
Rows are seeded as the app role in the tenant's session (RLS on), as the ports run.
"""

import datetime as dt
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.ai.infra.models import AiCall
from app.modules.ai.service import person_data as ai_port
from app.modules.analytics.infra.models import (
    Dashboard,
    DashboardPreference,
    Report,
    ReportExport,
    ReportFavourite,
    ReportFolder,
    ReportSchedule,
)
from app.modules.analytics.service import person_data as analytics_port
from app.modules.announcements.infra.models import (
    Announcement,
    AnnouncementDismissal,
    AnnouncementFollow,
)
from app.modules.announcements.service import person_data as announcements_port
from app.modules.identity_access import ErasureBatch, PersonData
from app.modules.knowledge.infra.models import (
    KbArticle,
    KbArticleVersion,
    KbTopic,
    KbType,
    KbVote,
)
from app.modules.knowledge.service import person_data as knowledge_port
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import Org, World

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the incidents fixture, re-used

PORTS: tuple[PersonData, ...] = (
    analytics_port.RECIPIENTS,
    knowledge_port.PORT,
    analytics_port.PORT,
    announcements_port.PORT,
    ai_port.PORT,
)
NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)


async def _in_tenant(world: World, org: Org, body):  # type: ignore[no-untyped-def]  # noqa: ANN001, ANN202 - a test helper taking a coroutine function
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            return await body(session)
    finally:
        await database.dispose()


async def _flush(session: AsyncSession, org: Org) -> None:
    """New rows take the tenant's ID (the app sets it in its repositories)."""
    for row in session.new:
        row.tenant_id = org.tenant
    await session.flush()


async def _seed(session: AsyncSession, org: Org, person: uuid.UUID, tag: str) -> None:
    """One of everything for `person`, plus a recipient entry on someone else's schedule."""
    code = f"erase_{tag}"
    session.add(KbType(code=code, review_months=12))
    topic = KbTopic(depth=1, names={"en": f"T {tag}"}, owner_id=person)
    session.add(topic)
    await _flush(session, org)
    article = KbArticle(display_id=f"KB-{tag}", topic_id=topic.id, type_code=code, owner_id=person)
    empty = KbArticle(
        display_id=f"KB-{tag}-e",
        topic_id=topic.id,
        type_code=code,
        owner_id=person,
        created_by=person,
    )
    session.add_all([article, empty])
    await _flush(session, org)
    live = KbArticleVersion(article_id=article.id, language="en", number=1, title="Live")
    live.status = "published"
    draft = KbArticleVersion(
        article_id=empty.id, language="en", number=1, title="Unsent", created_by=person
    )
    draft.status, draft.body_html = "draft", "<p>their words</p>"
    session.add_all([live, draft])
    await _flush(session, org)
    session.add(KbVote(article_id=article.id, version_id=live.id, person_id=person, helpful=True))
    session.add(ReportFavourite(user_id=person, report_ref=f"built_in.{tag}"))
    session.add(DashboardPreference(user_id=person))
    session.add(
        ReportExport(
            id=uuid.uuid4(),
            requested_by=person,
            title="Export",
            definition={},
            format="csv",
            content="summary",
            language="en",
            time_zone="UTC",
        )
    )
    session.add(Dashboard(name=f"Mine {tag}", owner_id=person, body={}, shared=False))
    session.add(Dashboard(name=f"Ours {tag}", owner_id=person, body={}, shared=True))
    session.add(Report(name=f"Report {tag}", owner_id=person, definition={}))
    session.add(ReportFolder(name=f"Folder {tag}", owner_id=person))
    schedule = {
        "title": "Weekly",
        "report_ref": f"built_in.{tag}",
        "frequency": "weekly",
        "at_time": dt.time(8),
        "time_zone": "UTC",
        "start_date": dt.date(2026, 11, 1),
        "format": "csv",
    }
    session.add(ReportSchedule(owner_id=person, status="active", **schedule))
    session.add(ReportSchedule(owner_id=org.admin, recipient_users=[str(person)], **schedule))
    note = Announcement(display_id=f"ANN-{tag}", title="Note", body="Body", owner_id=person)
    session.add(note)
    await _flush(session, org)
    session.add(AnnouncementFollow(announcement_id=note.id, user_id=person))
    session.add(AnnouncementDismissal(announcement_id=note.id, user_id=person))
    session.add(AiCall(user_id=person, feature="summary", provider="fake", model="m", status="ok"))
    await _flush(session, org)


async def _run(world: World, org: Org, person: uuid.UUID, successor: uuid.UUID) -> dict[str, int]:
    """Every port to the end, as the job runs them (one session a batch)."""
    counts: dict[str, int] = {}
    for port in sorted(PORTS, key=lambda p: (p.order, p.module)):
        cursor: str | None = None
        while True:

            async def step(
                session: AsyncSession, cursor: str | None = cursor, port: PersonData = port
            ) -> ErasureBatch:
                return await port.erase_person(
                    session, person, successor_id=successor, keep_files={}, now=NOW, cursor=cursor
                )

            batch = await _in_tenant(world, org, step)
            assert set(batch.counts) <= port.kinds, port.module
            for kind, n in batch.counts.items():
                counts[kind] = counts.get(kind, 0) + n
            if batch.cursor is None:
                break
            cursor = batch.cursor
    return counts


async def _owned(world: World, org: Org, person: uuid.UUID) -> dict[str, int]:
    """What `person` still has in the org's tenant (by table; explicit tenant filter)."""
    checks: tuple[tuple[str, str], ...] = (
        ("kb_votes", "person_id"),
        ("kb_topics", "owner_id"),
        ("report_favourites", "user_id"),
        ("dashboard_preferences", "user_id"),
        ("report_exports", "requested_by"),
        ("dashboards", "owner_id"),
        ("reports", "owner_id"),
        ("report_folders", "owner_id"),
        ("announcement_follows", "user_id"),
        ("announcement_dismissals", "user_id"),
        ("announcements", "owner_id"),
        ("ai_calls", "user_id"),
    )
    found: dict[str, int] = {}
    for table, column in checks:
        rows = await world.sql(
            f"SELECT count(*) AS n FROM {table} WHERE tenant_id = $1 AND {column} = $2",  # noqa: S608 - fixed names
            org.tenant,
            person,
        )
        found[table] = int(rows[0]["n"])
    live = await world.sql(
        "SELECT count(*) AS n FROM kb_articles WHERE tenant_id = $1 AND owner_id = $2",
        org.tenant,
        person,
    )
    found["kb_articles"] = int(live[0]["n"])
    schedules = await world.sql(
        "SELECT count(*) AS n FROM report_schedules WHERE tenant_id = $1"
        " AND (owner_id = $2 OR recipient_users @> jsonb_build_array($3::text))",
        org.tenant,
        person,
        str(person),
    )
    found["report_schedules"] = int(schedules[0]["n"])
    return found


async def test_lane_c_ports_erase_move_and_touch_nobody_else(world: World) -> None:
    org, other = world.a, world.b
    for target, who, tag in (
        (org, org.tech_b, "b"),
        (org, org.tech_a, "a"),
        (other, other.tech_b, "o"),
    ):
        await _in_tenant(world, target, lambda s, t=target, w=who, g=tag: _seed(s, t, w, g))
    before_a = await _owned(world, org, org.tech_a)
    before_other = await _owned(world, other, other.tech_b)
    outbox_before = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1", org.tenant
    )

    counts = await _run(world, org, org.tech_b, org.tech_a)

    assert counts == {
        "report_recipients_removed": 1,
        "kb_votes_deleted": 1,
        "kb_topics_moved": 1,
        "kb_articles_moved": 2,
        "kb_drafts_removed": 1,
        "kb_articles_removed": 1,
        "report_favourites_deleted": 1,
        "dashboard_preferences_deleted": 1,
        "report_exports_deleted": 1,
        "dashboards_deleted": 1,
        "dashboards_moved": 1,
        "reports_moved": 1,
        "report_folders_moved": 1,
        "report_schedules_moved": 1,
        "announcement_follows_deleted": 1,
        "announcement_dismissals_deleted": 1,
        "announcements_moved": 1,
        "ai_calls_deleted": 1,
    }
    assert set(counts.values()) == {1, 2}
    # Nothing of theirs is left; the successor holds what moved; the other tenant is untouched.
    assert set((await _owned(world, org, org.tech_b)).values()) == {0}
    after_a = await _owned(world, org, org.tech_a)
    moved = {"kb_topics": 1, "kb_articles": 2, "dashboards": 1, "reports": 1}
    moved |= {"report_folders": 1, "announcements": 1, "report_schedules": 1}
    assert after_a == {t: n + moved.get(t, 0) for t, n in before_a.items()}
    assert await _owned(world, other, other.tech_b) == before_other

    # The moved schedule is paused for its new owner; the unsent draft is blank and gone.
    paused = await world.sql(
        "SELECT status, paused_reason FROM report_schedules"
        " WHERE tenant_id = $1 AND owner_id = $2 AND report_ref = 'built_in.b'",
        org.tenant,
        org.tech_a,
    )
    assert [(r["status"], r["paused_reason"]) for r in paused] == [("paused", "owner_changed")]
    drafts = await world.sql(
        "SELECT title, body_html, deleted_at FROM kb_article_versions"
        " WHERE tenant_id = $1 AND created_by = $2",
        org.tenant,
        org.tech_b,
    )
    assert [(r["title"], r["body_html"], r["deleted_at"] is not None) for r in drafts] == [
        ("-", "", True)
    ]
    # Open screens follow: each moved or removed object wrote its event.
    outbox_after = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1", org.tenant
    )
    assert outbox_after[0]["n"] - outbox_before[0]["n"] >= 10

    # Twice is the same: nothing more to do.
    again = await _run(world, org, org.tech_b, org.tech_a)
    assert set(again.values()) == {0}
    assert await _owned(world, org, org.tech_a) == after_a


async def test_an_export_file_is_deleted_or_the_step_retries(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stored export's file goes before its row; no file store = a coded, retried failure."""
    from app.modules.identity_access import ErasureStepFailed  # noqa: PLC0415

    org = world.a
    person = org.requester

    async def seed(session: AsyncSession) -> None:
        row = ReportExport(
            id=uuid.uuid4(),
            requested_by=person,
            title="Stored",
            definition={},
            format="csv",
            content="summary",
            language="en",
            time_zone="UTC",
        )
        row.object_key = f"exports/{row.id}.csv"
        session.add(row)
        await _flush(session, org)

    await _in_tenant(world, org, seed)

    async def erase(session: AsyncSession) -> ErasureBatch:
        return await analytics_port.PORT.erase_person(
            session, person, successor_id=org.admin, keep_files={}, now=NOW, cursor="exports"
        )

    monkeypatch.setattr(analytics_port, "storage_factory", lambda: None)
    with pytest.raises(ErasureStepFailed) as failed:
        await _in_tenant(world, org, erase)
    assert failed.value.code == "erasure_storage_unavailable"

    deleted: list[str] = []

    class Store:
        async def delete(self, key: str) -> None:
            deleted.append(key)

    monkeypatch.setattr(analytics_port, "storage_factory", Store)
    batch = await _in_tenant(world, org, erase)
    assert batch.counts == {"report_exports_deleted": 1}
    assert len(deleted) == 1
    assert deleted[0].startswith("exports/")
    left = await world.sql(
        "SELECT count(*) AS n FROM report_exports WHERE tenant_id = $1 AND requested_by = $2",
        org.tenant,
        person,
    )
    assert left[0]["n"] == 0


async def test_another_tenants_session_sees_none_of_the_rows(world: World) -> None:
    """The ports read through RLS: another tenant's session sees none of this tenant's rows."""
    org, other = world.a, world.b

    async def look(session: AsyncSession) -> int:
        return len(
            list(await session.scalars(select(AiCall.id).where(AiCall.tenant_id == org.tenant)))
        )

    assert await _in_tenant(world, other, look) == 0
