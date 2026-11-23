"""How long a large asset import takes (WP-049b S4b, REQ-AST-053 AC1; coordinator 2026-11-11).

Opt-in: SUPPORTX_ASSET_IMPORT_SCALE_ROWS sets the number of rows (the target is 20,000). It runs
by hand on the audit-scale workflow (workflow_dispatch, `asset_import_rows`), on a CI runner
rather than a loaded laptop, and prints the dry run's and the real run's times. The figure
decides whether batched inserts come before the polish round (over about 10 minutes for 20,000
rows: yes). It checks the counts too, so a fast but wrong run never passes.
"""

import asyncio
import json
import os
import time
import uuid
from pathlib import Path

import pytest

from app.modules.assets.service.imports import run_asset_imports
from tests.db import test_incidents_api
from tests.db.test_asset_bulk_merge_import_api import _import, _job, _run
from tests.db.test_assets_api import _product
from tests.db.test_incidents_api import World
from tests.db.test_knowledge_api import _match

pytestmark = [pytest.mark.db, pytest.mark.scale]

world = test_incidents_api.world  # the incident world fixture, reused

ROWS = int(os.environ.get("SUPPORTX_ASSET_IMPORT_SCALE_ROWS", "0"))
REPORT = os.environ.get("SUPPORTX_ASSET_IMPORT_SCALE_REPORT")


@pytest.mark.skipif(ROWS <= 0, reason="set SUPPORTX_ASSET_IMPORT_SCALE_ROWS to run the volume test")
async def test_a_large_asset_import_checks_then_runs_and_reports_its_time(world: World) -> None:
    a = world.a
    product = f"Scale laptop {uuid.uuid4().hex[:6]}"
    await _product(world, a, "laptop", product)
    lines = ["Name,Product,Serial number,Location"]
    lines += [f"Scale asset {n},{product},SCALE-{n:06d},Rack {n % 40}" for n in range(1, ROWS + 1)]
    content = ("\n".join(lines) + "\n").encode()

    started = await _import(world, a, content, name="scale.csv")
    assert started.status_code == 201, started.text
    began = time.monotonic()
    await _run(world, run_asset_imports)
    dry_seconds = time.monotonic() - began
    checked = await _job(world, a, started.json())
    assert checked["status"] == "checked", checked
    assert (checked["created_count"], checked["failed_count"]) == (ROWS, 0)

    ran = await world.call(
        "POST",
        f"/assets/imports/{checked['id']}/run",
        a,
        a.admin,
        headers=_match(checked["version"]),
    )
    assert ran.status_code == 200, ran.text
    began = time.monotonic()
    await _run(world, run_asset_imports)
    run_seconds = time.monotonic() - began
    done = await _job(world, a, checked)
    assert done["status"] == "done", done
    assert done["created_count"] == ROWS
    stored = await world.sql(
        "SELECT count(*) AS n FROM assets WHERE tenant_id = $1 AND serial_number LIKE 'SCALE-%'",
        a.tenant,
    )
    assert stored[0]["n"] == ROWS

    figures = {
        "rows": ROWS,
        "dry_run_seconds": round(dry_seconds, 1),
        "run_seconds": round(run_seconds, 1),
        "ms_per_row_run": round(1000 * run_seconds / ROWS, 1),
    }
    print(f"asset import scale: {json.dumps(figures)}")  # noqa: T201 - the job summary's figure
    if REPORT:
        await asyncio.to_thread(Path(REPORT).write_text, json.dumps(figures), encoding="utf-8")
