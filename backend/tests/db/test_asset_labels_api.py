"""Asset labels over HTTP and in the worker (WP-049b s3; 0134; REQ-AST-039).

The incident world; object storage is an in-memory fake (nothing touches the dev stack's
MinIO), and the PDF renderer is a fake that records what it was asked to print (the real one
needs the worker image: app/modules/assets/tests/test_labels_pdf.py).
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.assets.domain.labels import Label
from app.modules.assets.service import labels as service
from tests.db import test_incidents_api
from tests.db.test_asset_audits_api import _asset
from tests.db.test_asset_financials_api import _events
from tests.db.test_incidents_api import Org, World, problem, role
from tests.db.test_knowledge_api import _new
from tests.db.test_report_exports import MemoryStorage

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets/labels"
NEW_TABLES = ("asset_label_jobs", "asset_label_prints")


class FakeRenderer:
    """Records each job's labels; returns a tiny 'PDF'."""

    def __init__(self) -> None:
        self.calls: list[list[Label]] = []

    def __call__(self, labels: list[Label], **options: Any) -> bytes:  # noqa: ANN401 - layout etc.
        del options
        self.calls.append(list(labels))
        return b"%PDF-1.7 fake " + str(len(labels)).encode()


@pytest_asyncio.fixture
async def printing(world: World) -> AsyncIterator[tuple[World, MemoryStorage, FakeRenderer]]:
    storage, renderer = MemoryStorage(), FakeRenderer()
    service.set_label_storage(storage)
    service.set_label_renderer(renderer)
    try:
        yield world, storage, renderer
    finally:
        service.set_label_storage(None)
        service._state.pop("render", None)  # noqa: SLF001 - found again by the next process


async def _print(world: World, org: Org, user: uuid.UUID, **body: Any) -> Any:  # noqa: ANN401 - JSON
    return await world.call("POST", BASE, org, user, json=body, headers=_new())


async def _build(world: World, org: Org, job_id: str) -> None:
    """What the consumers worker does for one requested job."""
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        await service.build_labels(
            session,
            uuid.UUID(job_id),
            service.LabelWorker(
                storage=service.label_storage(world.app.state.settings),
                render=service.label_renderer(),
                settings=world.app.state.settings,
            ),
        )


async def test_039_ac1_one_hundred_assets_make_one_pdf_in_the_worker(
    printing: tuple[World, MemoryStorage, FakeRenderer],
) -> None:
    world, storage, renderer = printing
    a = world.a
    assets = [await _asset(world, a, f"Bulk {n}") for n in range(100)]
    asked = await _print(world, a, a.tech_a, asset_ids=[x["id"] for x in assets], layout="cable")
    assert asked.status_code == 202, asked.text
    job = asked.json()
    assert (job["status"], job["item_count"], job["done"]) == ("running", 100, 0)
    assert renderer.calls == []  # never inside the request
    (requested,) = await _events(world, a, "assets.label.requested")
    assert set(requested["payload"]) == {"job_id", "requested_by"}
    await _build(world, a, job["id"])
    (labels,) = renderer.calls
    assert len(labels) == 100
    # The QR content is only the console link to the asset.
    assert labels[0].content.endswith(f"/assets/{assets[0]['id']}")
    assert labels[0].content.startswith("http")
    ready = (await world.call("GET", f"{BASE}/jobs", a, a.tech_a)).json()[0]
    assert (ready["status"], ready["pages"], ready["done"]) == ("ready", 100, 100)
    (printed,) = await _events(world, a, "assets.label.printed")
    assert (printed["payload"]["status"], printed["payload"]["problem"]) == ("ready", None)
    file = await world.call("GET", f"{BASE}/jobs/{job['id']}/file", a, a.tech_a)
    assert file.status_code == 200, file.text
    assert file.content.startswith(b"%PDF")
    assert file.headers["content-type"] == "application/pdf"
    # Only the person who asked downloads it.
    assert problem(await world.call("GET", f"{BASE}/jobs/{job['id']}/file", a, a.tech_b)) == (
        404,
        "asset_label_job_not_found",
    )
    assert len(storage.files) == 1


async def test_039_ac2_a_person_never_prints_an_asset_they_cannot_see(
    printing: tuple[World, MemoryStorage, FakeRenderer],
) -> None:
    world, _, _ = printing
    a, b = world.a, world.b
    at_s1 = await _asset(world, a, "At S1", site_id=str(a.s1))
    at_s2 = await _asset(world, a, "At S2", site_id=str(a.s2))
    # A requester with assets.view at their own sites only (requester: member of S1).
    viewer = await role(world, a, "Site viewer", [("assets.view", "site")])
    given = await world.call("PUT", f"/users/{a.requester}/roles/{viewer}", a, a.admin)
    assert given.status_code == 204, given.text
    assert (await _print(world, a, a.requester, asset_ids=[at_s1["id"]])).status_code == 202
    hidden = await _print(world, a, a.requester, asset_ids=[at_s1["id"], at_s2["id"]])
    assert problem(hidden) == (404, "asset_not_found")  # the whole job, naming none
    # No assets.view at all: refused; another tenant: not found.
    assert problem(await _print(world, a, a.requester2, asset_ids=[at_s1["id"]]))[0] == 403
    assert problem(await _print(world, b, b.admin, asset_ids=[at_s1["id"]])) == (
        404,
        "asset_not_found",
    )
    # Someone signed out learns nothing from the link the QR code holds: the API asks to sign in.
    anonymous = await world.client.get(f"/api/v1/assets/{at_s1['id']}")
    assert anonymous.status_code == 401
    assert "At S1" not in anonymous.text


async def test_039_ac3_every_print_and_reprint_writes_an_append_only_history_row(
    printing: tuple[World, MemoryStorage, FakeRenderer],
) -> None:
    world, _, _ = printing
    a = world.a
    asset = await _asset(world, a, "Reprinted")
    first = (await _print(world, a, a.tech_a, asset_ids=[asset["id"]], symbology="code128")).json()
    history = (
        await world.call("GET", f"{BASE}/prints", a, a.tech_a, params={"asset_id": asset["id"]})
    ).json()
    assert [(h["job_id"], h["reprint"], h["printed_by"]) for h in history] == [
        (first["id"], False, str(a.tech_a))
    ]
    again = await world.call(
        "POST", f"{BASE}/prints/{history[0]['id']}/reprint", a, a.tech_b, headers=_new()
    )
    assert again.status_code == 202, again.text
    assert again.json()["reprint_of"] == first["id"]
    history = (
        await world.call("GET", f"{BASE}/prints", a, a.tech_a, params={"asset_id": asset["id"]})
    ).json()
    assert [(h["reprint"], h["printed_by"], h["symbology"]) for h in history] == [
        (True, str(a.tech_b), "code128"),
        (False, str(a.tech_a), "code128"),
    ]
    # The application role may only read and add print rows.
    for statement in (
        "UPDATE asset_label_prints SET reprint = true",
        "DELETE FROM asset_label_prints",
    ):
        with pytest.raises(Exception, match="permission denied"):
            async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
                await session.execute(text(statement))


async def test_vendor_codes_and_jobs_that_fail_say_why(
    printing: tuple[World, MemoryStorage, FakeRenderer],
) -> None:
    world, _, renderer = printing
    a = world.a
    codes = await _print(world, a, a.tech_a, target="vendor_code", codes=["SN-1", " SN 2 "])
    assert codes.status_code == 202, codes.text
    await _build(world, a, codes.json()["id"])
    assert [label.content for label in renderer.calls[-1]] == ["SN-1", "SN 2"]
    blank = await _print(world, a, a.tech_a, target="vendor_code", codes=[" "])
    assert blank.status_code == 422
    # No renderer in this process: the job fails visibly, never silently.
    service.set_label_renderer(None)
    asset = await _asset(world, a, "No PDF")
    job = (await _print(world, a, a.tech_a, asset_ids=[asset["id"]])).json()
    await _build(world, a, job["id"])
    found = next(
        j
        for j in (await world.call("GET", f"{BASE}/jobs", a, a.tech_a)).json()
        if j["id"] == job["id"]
    )
    assert (found["status"], found["problem"]) == ("failed", "pdf_not_available")
    # No object storage (the test settings configure none): refused at once (503).
    service.set_label_storage(None)
    refused = await _print(world, a, a.tech_a, asset_ids=[asset["id"]])
    assert problem(refused) == (503, "storage_not_configured")


async def test_label_tables_are_isolated_by_rls(
    printing: tuple[World, MemoryStorage, FakeRenderer],
) -> None:
    world, _, _ = printing
    a, b = world.a, world.b
    asset = await _asset(world, a, "Mine only")
    assert (await _print(world, a, a.tech_a, asset_ids=[asset["id"]])).status_code == 202
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in NEW_TABLES:
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 0  # noqa: S608 - fixed names
        assert (await session.execute(text("UPDATE asset_label_jobs SET done = 1"))).rowcount == 0
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        job_id = await session.scalar(text("SELECT id FROM asset_label_jobs LIMIT 1"))
    with pytest.raises(Exception, match="row-level security"):
        async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO asset_label_prints (tenant_id, id, job_id, target, layout,"
                    " symbology, item_count) VALUES (:t, :i, :j, 'asset', 'cable', 'qr', 1)"
                ),
                {"t": a.tenant, "i": uuid.uuid4(), "j": job_id},
            )
    assert (await world.call("GET", f"{BASE}/prints", b, b.admin)).json() == []
