"""`make dev-subscription` (tooling/dev_subscription.py): options, plan changes, the real write."""

from datetime import UTC, datetime

import pytest

from app.modules.licensing import Edition, LimitKey
from conftest import create_tenant
from tests.events.conftest import outbox_rows
from tooling import dev_subscription
from tooling.db_testing import ThrowawayDatabase
from tooling.seed_dev import OTHER_TENANT_ID


def test_only_given_options_become_changes() -> None:
    tenant, changes = dev_subscription.parse_args(["--tenant", "other"])
    assert (tenant, changes) == (OTHER_TENANT_ID, {})
    _, changes = dev_subscription.parse_args(
        [
            "--tenant",
            str(OTHER_TENANT_ID),
            "--technicians",
            "1",
            "--assets",
            "unlimited",
            "--expires",
            "2026-09-01",
            "--status",
            "suspended",
            "--edition",
            "essentials",
        ]
    )
    assert changes == {
        "technicians": 1,
        "assets": None,
        "expires_at": datetime(2026, 9, 2, tzinfo=UTC),  # valid through the whole named day
        "status": "suspended",
        "edition": Edition.ESSENTIALS,
    }
    assert dev_subscription.parse_args(["--tenant", "demo", "--expires", "never"])[1] == {
        "expires_at": None
    }


def test_unknown_tenant_alias_is_refused() -> None:
    with pytest.raises(SystemExit):
        dev_subscription.parse_args(["--tenant", "nobody"])


def test_changes_apply_on_top_of_the_current_plan() -> None:
    plan = dev_subscription.changed_plan(None, {"technicians": 3, "expires_at": None})
    assert plan.edition is Edition.PROFESSIONAL
    assert dict(plan.limits) == {LimitKey.TECHNICIANS: 3}
    again = dev_subscription.changed_plan(plan, {"assets": 10})
    assert dict(again.limits) == {LimitKey.TECHNICIANS: 3, LimitKey.ASSETS: 10}
    assert "technicians" in dev_subscription.describe(again)
    assert "nothing is licensed" in dev_subscription.describe(None)


@pytest.mark.db
async def test_run_shows_and_changes_the_plan(migrated_db: ThrowawayDatabase) -> None:
    tenant = await create_tenant(migrated_db.migrator_url, "Tooling", edition="professional")
    shown = await dev_subscription.run(migrated_db.migrator_url, tenant, {})
    assert "edition: professional" in shown
    changed = await dev_subscription.run(migrated_db.migrator_url, tenant, {"technicians": 1})
    assert changed.startswith(f"Tenant {tenant}: changed limits")
    events = [r for r in await outbox_rows(migrated_db.admin_url) if r["tenant_id"] == tenant]
    assert [r["event_type"] for r in events] == ["licensing.entitlement.changed"]
    unchanged = await dev_subscription.run(migrated_db.migrator_url, tenant, {"technicians": 1})
    assert "changed nothing" in unchanged
