"""Reports, dashboards and schedules honour field access per role (ADR-047 §5; lane C's slice).

- A report naming a field the viewer's roles hide or mask (filter, column or sort; groupings
  too, for the field types that group) is
  refused as `field_not_permitted`, never as an unknown field and never with its values.
- A scheduled report is built per recipient with their access: a recipient who may not see a
  field is not sent the file; the others are.
- A schedule whose owner may no longer see a field it uses pauses (`field_not_permitted`)
  before any file is made: a schedule mails with its owner's access.
"""

import uuid
from typing import Any

import pytest

from app.core.config import Settings
from tests.db import test_report_schedules, test_reports_api
from tests.db.test_field_access_reads import _custom_field, _rule
from tests.db.test_incidents_api import CONSOLE, Org, World
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db
world = test_reports_api.world
reports = test_reports_api.reports
mailing = test_report_schedules.mailing
_run_due = test_report_schedules._run_due  # noqa: SLF001 - the schedules tests' own sweep


async def _run(world: World, org: Org, user: uuid.UUID, definition: dict[str, Any]) -> Any:  # noqa: ANN401 - the response
    return await world.call(
        "POST",
        "/reports/run",
        org,
        user,
        json={"definition": {"entity": "incident", **definition}, "language": "en"},
        headers=CONSOLE,
    )


async def test_a_withheld_field_is_refused_as_not_permitted_wherever_it_is_named(
    reports: World,
) -> None:
    world, a = reports, reports.a
    band = await _custom_field(world, a, "Salary band")
    await world.create(a, a.admin, group_id=str(a.ga), custom={band: "B7"})
    await _rule(world, a, "technician", f"custom.{band}", "masked")
    name = f"custom.{band}"
    uses = (
        {"filter": {"field": name, "op": "eq", "value": "B7"}, "measures": ["count"]},
        {"columns": ["display_id", name], "measures": ["count"]},
        {"columns": ["display_id"], "sort": [{"field": name}], "measures": ["count"]},
    )
    for use in uses:
        refused = await _run(world, a, a.tech_a, use)
        assert refused.status_code == 403, (use, refused.text)
        assert refused.json()["code"] == "field_not_permitted", use
        assert "B7" not in refused.text
        allowed = await _run(world, a, a.admin, use)
        assert allowed.status_code == 200, (use, allowed.text)
    # Without the field the technician's report runs as before.
    assert (await _run(world, a, a.tech_a, {"measures": ["count"]})).status_code == 200


async def _scheduled(world: World, a: Org, field: str, title: str) -> dict[str, Any]:
    """The admin's saved report filtering on `field`, mailed weekly to the admin and tech_a."""
    saved = await world.call(
        "POST",
        "/reports",
        a,
        a.admin,
        json={
            "name": title,
            "definition": {
                "entity": "incident",
                "filter": {"field": field, "op": "eq", "value": "B7"},
                "measures": ["count"],
            },
        },
        headers={**CONSOLE, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert saved.status_code == 201, saved.text
    made = await world.call(
        "POST",
        "/reports/schedules",
        a,
        a.admin,
        json=test_report_schedules._body(  # noqa: SLF001 - the schedules tests' own body
            a,
            title=title,
            report_ref=saved.json()["id"],
            recipient_users=[str(a.admin), str(a.tech_a)],
            recipient_groups=[],
        ),
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _sent_to(world: World, a: Org, title: str) -> set[str]:
    mails = await world.sql(
        "SELECT m.recipients FROM mail_messages m"
        " WHERE m.tenant_id = $1 AND m.kind = 'report' AND m.subject LIKE $2",
        a.tenant,
        f"%{title}%",
    )
    return {m["recipients"][0] for m in mails}


async def _email(world: World, user: uuid.UUID) -> str:
    rows = await world.sql("SELECT email FROM users WHERE id = $1", user)
    return str(rows[0]["email"])


async def test_a_recipient_who_may_not_see_a_field_gets_no_file(
    mailing: tuple[World, Settings], migrated_db: ThrowawayDatabase
) -> None:
    world, settings = mailing
    a = world.a
    band = await _custom_field(world, a, "Pay band")
    await _scheduled(world, a, f"custom.{band}", "Pay bands")
    await _rule(world, a, "technician", f"custom.{band}", "masked")

    await _run_due(world, migrated_db, a, settings)

    sent = await _sent_to(world, a, "Pay bands")
    assert await _email(world, a.admin) in sent
    assert await _email(world, a.tech_a) not in sent
    item = next(
        i
        for i in (await world.call("GET", "/reports/schedules", a, a.admin)).json()["items"]
        if i["title"] == "Pay bands"
    )
    assert (item["last_sent"], item["last_failed"], item["status"]) == (1, 1, "active")


async def test_a_schedule_pauses_when_its_owner_may_no_longer_see_a_field(
    mailing: tuple[World, Settings], migrated_db: ThrowawayDatabase
) -> None:
    world, settings = mailing
    a = world.a
    band = await _custom_field(world, a, "Bonus band")
    made = await _scheduled(world, a, f"custom.{band}", "Bonus bands")
    await _rule(world, a, "tenant_admin", f"custom.{band}", "hidden")

    await _run_due(world, migrated_db, a, settings)

    assert await _sent_to(world, a, "Bonus bands") == set()  # nobody: not even the technician
    rows = await world.sql(
        "SELECT status, paused_reason, last_result FROM report_schedules"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(made["id"]),
    )
    assert (rows[0]["status"], rows[0]["paused_reason"], rows[0]["last_result"]) == (
        "paused",
        "field_not_permitted",
        "field_not_permitted",
    )
