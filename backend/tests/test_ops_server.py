"""The internal operations endpoint: probes and Prometheus metrics (WP-014)."""

import re

import httpx

from app.core.config import Settings
from app.core.ops_server import OpsServer
from workers.metrics import METER_NAME, build_meter_provider


async def test_probes_and_metrics() -> None:
    ready = False
    server = OpsServer("127.0.0.1", 0, ready=lambda: ready)
    provider = build_meter_provider(
        Settings.load(env_file=None, profile="test", metrics_exporter="prometheus")
    )
    counter = provider.get_meter(METER_NAME).create_counter("supportx.ops_test.events")
    counter.add(3)
    await server.start()
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.port}") as client:
            assert (await client.get("/healthz")).status_code == 200
            # Not ready until the worker has connected and subscribed.
            assert (await client.get("/readyz")).status_code == 503
            ready = True
            assert (await client.get("/readyz")).status_code == 200
            metrics = await client.get("/metrics")
            assert metrics.status_code == 200
            assert "text/plain" in metrics.headers["content-type"]
            assert re.search(
                r"^supportx_ops_test_events_total\{[^}]*\} 3\.0$", metrics.text, re.MULTILINE
            )
            assert (await client.get("/elsewhere")).status_code == 404
            assert (await client.post("/metrics")).status_code == 405
            head = await client.head("/healthz")
            assert (head.status_code, head.content) == (200, b"")
    finally:
        await server.stop()
        provider.shutdown()
