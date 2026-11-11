"""Scan history and the overdue-scan rule (WP-049b s3; 0134; REQ-AST-054, 056).

Scans come in through the public port `app.modules.assets.record_scan` (discovery will call it);
the clean-up and the rule run as their scheduled jobs do, per tenant with app.tenant_id set.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, text

from app.core.errors import ValidationFailed
from app.core.tenancy import TenantContext
from app.modules.assets import ScanFailure, ScanResult, ScanSource, ScanType, record_scan
from app.modules.assets.infra.models import AssetScan
from app.modules.assets.service import scans
from app.modules.audit.infra.models import AuditEntry
from tests.db import test_incidents_api
from tests.db.test_asset_audits_api import _asset
from tests.db.test_asset_financials_api import _events, _fresh
from tests.db.test_asset_moves_api import _states
from tests.db.test_assets_api import _types
from tests.db.test_incidents_api import Org, World, field_codes, problem
from tests.db.test_knowledge_api import _match, _new

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

RULE = "/assets/overdue-rule"
NEW_TABLES = ("asset_scans", "asset_overdue_rules", "asset_overdue_runs")
DISK = {"kind": "hardware_added", "category": "disk", "name": "NVMe SSD", "model": "MZ-V8V1T0",
        "capacity": "1 TB"}  # fmt: skip


async def _scan(org: Org, world: World, asset: dict[str, Any], days_ago: float, **kw: Any) -> None:  # noqa: ANN401 - port options
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        await record_scan(
            session,
            asset_id=uuid.UUID(asset["id"]),
            scanned_at=datetime.now(UTC) - timedelta(days=days_ago),
            source=kw.pop("source", ScanSource.AGENT),
            result=kw.pop("result", ScanResult.OK),
            **kw,
        )


async def _list(
    world: World, org: Org, asset: dict[str, Any], user: uuid.UUID | None = None
) -> Any:  # noqa: ANN401 - httpx response
    return await world.call("GET", f"/assets/{asset['id']}/scans", org, user or org.admin)


async def test_054_ac1_and_ac3_scans_list_what_changed_and_why_a_scan_failed(
    world: World,
) -> None:
    a, b = world.a, world.b
    asset = await _asset(world, a, "Scanned")
    await _scan(a, world, asset, 2, scan_type=ScanType.HARDWARE, changes=[DISK])
    await _scan(
        a, world, asset, 1, source=ScanSource.PROBE, result=ScanResult.FAILED,
        failure_reason=ScanFailure.CREDENTIALS_REFUSED,
    )  # fmt: skip
    found = await _list(world, a, asset, a.tech_a)  # assets.view reads them
    assert found.status_code == 200, found.text
    failed, disk = found.json()["items"]
    assert (failed["result"], failed["failure_reason"], failed["source"]) == (
        "failed", "credentials_refused", "probe",
    )  # fmt: skip
    assert disk["changes"] == [{**DISK, "serial": None, "version": None, "publisher": None}]
    # Only a good scan moves the last-scanned time; a change adds a line to the asset's history.
    fresh = await _fresh(world, a, asset)
    history = (await world.call("GET", f"/assets/{asset['id']}/history", a, a.admin)).json()
    assert any(c["field"] == "scan" for e in history["items"] for c in e["changes"])
    assert fresh["version"] == asset["version"]  # a scan is no save of the asset
    (event, _) = await _events(world, a, "assets.scan.recorded")
    assert set(event["payload"]) == {"asset_id", "scan_id", "result", "changes"}
    # The port refuses what it does not know, and a failed scan must say why.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        asset_id = uuid.UUID(asset["id"])
        with pytest.raises(ValidationFailed):
            await record_scan(
                session, asset_id=asset_id, scanned_at=datetime.now(UTC), source=ScanSource.IMPORT,
                result=ScanResult.OK, changes=[{"kind": "exploded", "name": "x"}],
            )  # fmt: skip
        with pytest.raises(ValidationFailed):
            await record_scan(
                session, asset_id=asset_id, scanned_at=datetime.now(UTC), source=ScanSource.IMPORT,
                result=ScanResult.FAILED,
            )  # fmt: skip
    assert (await _list(world, b, asset)).status_code == 404
    assert problem(await _list(world, a, asset, a.requester))[0] == 403


async def test_054_ac2_the_clean_up_removes_old_scans_and_keeps_the_asset_and_its_history(
    world: World,
) -> None:
    a = world.a
    asset = await _asset(world, a, "Old scans")
    await _scan(a, world, asset, 400, changes=[DISK])  # past the 6 months kept by default
    await _scan(a, world, asset, 10)
    before = (await world.call("GET", f"/assets/{asset['id']}/history", a, a.admin)).json()
    await scans.scan_cleanup_sweep(world.app.state.db, world.app.state.settings)
    left = (await _list(world, a, asset)).json()["items"]
    assert len(left) == 1
    after = (await world.call("GET", f"/assets/{asset['id']}/history", a, a.admin)).json()
    assert after["items"] == before["items"]  # its history lines stay
    assert (await world.call("GET", f"/assets/{asset['id']}", a, a.admin)).status_code == 200
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        summary = await session.scalar(
            select(AuditEntry)
            .where(AuditEntry.action == "asset_scan.cleaned_up")
            .order_by(AuditEntry.occurred_at.desc())
        )
        assert summary is not None
        assert summary.details["deleted"] == 1
        assert summary.details["cutoff"]
        assert await session.scalar(select(func.count()).select_from(AssetScan)) == 1


async def _rule(world: World, org: Org) -> dict[str, Any]:
    found = await world.call("GET", RULE, org, org.admin)
    assert found.status_code == 200, found.text
    return dict(found.json())


async def test_056_ac1_and_ac2_a_laptop_not_scanned_for_61_days_moves_to_missing(
    world: World,
) -> None:
    a = world.a
    laptops = (await _types(world, a))["laptop"]["id"]
    states = await _states(world, a)
    overdue = await _asset(world, a, "Forgotten laptop")
    recent = await _asset(world, a, "Seen laptop")
    never = await _asset(world, a, "Never scanned")
    await _scan(a, world, overdue, 61)
    await _scan(a, world, recent, 59)
    rule = await _rule(world, a)
    assert (rule["enabled"], rule["days"], rule["action"]) == (False, 60, "move_state")  # off
    wanted = {
        "enabled": True, "days": 60, "product_type_ids": [laptops], "action": "move_state",
        "state_id": states["missing"],
    }  # fmt: skip
    preview = await world.call("POST", f"{RULE}/preview", a, a.admin, json=wanted)
    assert preview.json() == {"count": 1}  # AC2: what it would affect now
    assert problem(await world.call("POST", f"{RULE}/preview", a, a.tech_a, json=wanted))[0] == 403
    stale = await world.call(
        "PATCH", RULE, a, a.admin, json=wanted, headers=_match(rule["version"] + 1)
    )
    assert problem(stale) == (409, "version_conflict")
    saved = await world.call(
        "PATCH", RULE, a, a.admin, json=wanted, headers=_match(rule["version"])
    )
    assert saved.status_code == 200, saved.text
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        run = await scans.run_rule(session)
        assert run is not None
        assert run.changed_count == 1
    assert (await _fresh(world, a, overdue))["state_id"] == states["missing"]
    assert (await _fresh(world, a, recent))["state_id"] != states["missing"]
    assert (await _fresh(world, a, never))["state_id"] != states["missing"]
    history = (await world.call("GET", f"/assets/{overdue['id']}/history", a, a.admin)).json()
    latest = history["items"][0]
    assert (latest["source"], latest["origin"]) == ("rule", {
        "kind": "asset_overdue_rule", "audit_id": None, "display_id": None, "name": None,
    })  # fmt: skip
    runs = (await world.call("GET", f"{RULE}/runs", a, a.admin)).json()
    assert [(r["changed_count"], r["changed"][0]["asset_id"]) for r in runs] == [(1, overdue["id"])]
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await scans.run_rule(session) is None  # nothing new: no empty run recorded
    (event,) = [
        e
        for e in await _events(world, a, "assets.overdue_rule.changed")
        if e["payload"]["action"] == "ran"
    ]
    assert event["payload"]["changed_count"] == 1


async def test_056_ac3_an_asset_the_rule_moved_to_the_trash_is_restored_with_its_history(
    world: World,
) -> None:
    a = world.a
    asset = await _asset(world, a, "Trashed by rule")
    await _scan(a, world, asset, 100)
    rule = await _rule(world, a)
    saved = await world.call(
        "PATCH", RULE, a, a.admin, headers=_match(rule["version"]),
        json={"enabled": True, "days": 90, "action": "trash"},
    )  # fmt: skip
    assert saved.status_code == 200, saved.text
    await scans.overdue_sweep(world.app.state.db, world.app.state.settings)
    assert (await world.call("GET", f"/assets/{asset['id']}", a, a.admin)).status_code == 404
    restored = await world.call(
        "POST", f"/assets/{asset['id']}/restore", a, a.admin, headers=_new()
    )
    assert restored.status_code == 200, restored.text
    history = (await world.call("GET", f"/assets/{asset['id']}/history", a, a.admin)).json()
    items = history["items"]
    trash = [
        (c["old"], c["new"]) for e in items[:2] for c in e["changes"] if c["field"] == "deleted"
    ]
    assert trash == [(True, False), (False, True)]  # restored, after the rule's move to the trash
    assert (items[0]["origin"], items[1]["origin"]["kind"]) == (None, "asset_overdue_rule")
    assert items[-1]["kind"] == "created"  # all of it kept


async def test_scan_and_rule_tables_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    asset = await _asset(world, a, "Private scans")
    await _scan(a, world, asset, 70)
    rule = await _rule(world, a)
    await world.call(
        "PATCH", RULE, a, a.admin, headers=_match(rule["version"]),
        json={"enabled": True, "days": 60, "action": "trash"},
    )  # fmt: skip
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await scans.run_rule(session) is not None
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in NEW_TABLES:
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 0  # noqa: S608 - fixed names
        assert (await session.execute(text("DELETE FROM asset_scans"))).rowcount == 0
        assert (
            await session.execute(text("UPDATE asset_overdue_rules SET days = 1"))
        ).rowcount == 0
    with pytest.raises(Exception, match="row-level security"):
        async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO asset_overdue_runs (tenant_id, id, ran_at, days, action,"
                    " changed_count) VALUES (:t, :i, now(), 1, 'trash', 0)"
                ),
                {"t": a.tenant, "i": uuid.uuid4()},
            )
    # The app role may never change a scan or a run (append-only).
    for statement in (
        "UPDATE asset_scans SET result = 'ok'",
        "UPDATE asset_overdue_runs SET days = 2",
    ):
        with pytest.raises(Exception, match="permission denied"):
            async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
                await session.execute(text(statement))
    assert (await _rule(world, b))["enabled"] is False


async def test_056_the_rule_follows_the_life_cycle_and_never_forces_a_move(world: World) -> None:
    """A target no life cycle reaches is refused; an asset whose state has no move there is
    skipped, listed with its reason, and keeps its state (the coordinator, 2026-11-11)."""
    a = world.a
    states = await _states(world, a)
    made = await world.call(
        "POST", "/assets/states", a, a.admin, headers=_new(),
        json={"code": "with_courier", "names": {"en": "With courier"}, "category": "in_use"},
    )  # fmt: skip
    assert made.status_code == 201, made.text
    rule = await _rule(world, a)
    offered = (await world.call("GET", f"{RULE}/states", a, a.admin)).json()["state_ids"]
    assert states["missing"] in offered
    assert made.json()["id"] not in offered
    assert states["disposed"] not in offered
    refused = await world.call(
        "PATCH", RULE, a, a.admin, headers=_match(rule["version"]),
        json={"enabled": True, "days": 60, "action": "move_state", "state_id": made.json()["id"]},
    )  # fmt: skip
    assert refused.status_code == 422
    assert field_codes(refused) == {"state_id": "asset_overdue_state_unreachable"}
    # In repair has no move to missing: that asset is skipped, the one in stock is moved.
    stuck = await _asset(world, a, "In the workshop")
    moved = await world.call(
        "POST", f"/assets/{stuck['id']}/move", a, a.admin, headers=_match(stuck["version"]),
        json={"to_state_id": states["in_repair"], "reason": "Fan replaced"},
    )  # fmt: skip
    assert moved.status_code == 200, moved.text
    free = await _asset(world, a, "On the shelf")
    for asset in (stuck, free):
        await _scan(a, world, asset, 61)
    saved = await world.call(
        "PATCH", RULE, a, a.admin, headers=_match(rule["version"]),
        json={"enabled": True, "days": 60, "action": "move_state", "state_id": states["missing"]},
    )  # fmt: skip
    assert saved.status_code == 200, saved.text
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        run = await scans.run_rule(session)
        assert run is not None
        assert run.changed_count == 1
        assert {"asset_id": stuck["id"], "action": "skipped", "reason": "transition_not_allowed",
                "from_state_id": states["in_repair"]} in run.changed  # fmt: skip
    assert (await _fresh(world, a, stuck))["state_id"] == states["in_repair"]  # never forced
    assert (await _fresh(world, a, free))["state_id"] == states["missing"]
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await scans.run_rule(session) is None  # skipped before: not listed every hour
