"""SupportX only ever reads MonetX (ADR-017, D-001; the coordinator's S6 condition 1).

The client module names one HTTP method, GET, and no write verb, request body or other client;
the assumed OpenAPI fixture has GET operations only; and the stand-in serves the client's paths.
"""

import ast
import asyncio
from pathlib import Path

from app.modules.monitoring_integrations.infra.monetx_client import MonetXClient
from tests.monetx_fake import FakeMonetX

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "app/modules/monitoring_integrations/infra/monetx_client.py"
FIXTURE = ROOT / "tests/fixtures/monetx/monetx-openapi.yaml"
WRITE_VERBS = {"post", "put", "patch", "delete"}


def _strings(tree: ast.AST) -> set[str]:
    return {
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


def test_the_client_names_get_and_no_write_verb() -> None:
    tree = ast.parse(CLIENT.read_text(encoding="utf-8"))
    methods = {s.upper() for s in _strings(tree)} & {
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "HEAD",
        "OPTIONS",
    }
    assert methods == {"GET"}, methods
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
    }
    assert not (names & WRITE_VERBS), names & WRITE_VERBS
    bodies = [
        k for n in ast.walk(tree) if isinstance(n, ast.Call) for k in n.keywords if k.arg == "body"
    ]
    assert bodies == [], "a request body means a write"
    imports = {
        a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in n.names
    }
    assert not ({"httpx", "requests", "aiohttp"} & imports), "only through app/shared/egress"


def test_the_assumed_openapi_has_only_get_operations() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    paths = text.split("\npaths:\n", 1)[1].split("\ncomponents:", 1)[0]
    operations = {
        line.strip().rstrip(":")
        for line in paths.splitlines()
        if line.startswith("    ") and not line.startswith("     ")
    }
    assert operations == {"get"}, operations


def test_the_stand_in_serves_every_path_the_client_reads() -> None:
    fake = FakeMonetX(
        devices=[{"id": f"d{i}", "name": f"Host {i}", "kind": "server"} for i in range(3)],
        links=[{"id": "l1", "from": "d0", "to": "d1"}],
        health={"d0": {"status": "up", "problem_count": 0}},
        page_size=2,
    )
    client = MonetXClient(fake)

    async def run() -> tuple[int, int, int]:
        devices = await client.devices()
        links = await client.links()
        health = await client.health(["d0", "d9"])
        return len(devices), len(links), len(health)

    assert asyncio.run(run()) == (3, 1, 1)
    assert fake.reads_of("/api/v1/devices") == 2  # paged through the cursor
