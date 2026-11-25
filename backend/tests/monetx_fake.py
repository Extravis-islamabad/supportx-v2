"""A stand-in MonetX serving tests/fixtures/monetx/monetx-openapi.yaml (WP-053 S6; D-172).

In-process, at the client's transport boundary: it records every read (so a test can count them,
and prove the single-flight), refuses or fails on demand, and has no way to accept a write.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.modules.monitoring_integrations.infra.monetx_client import MonitoringUnavailableError


@dataclass
class FakeMonetX:
    """`devices`, `links` and `health` are what MonetX reports; `fail` makes every read fail."""

    devices: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)
    health: dict[str, dict[str, Any]] = field(default_factory=dict)
    fail: str | None = None
    page_size: int = 500
    reads: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    async def read(self, path: str, query: Mapping[str, str]) -> Any:  # noqa: ANN401 - JSON
        """GET `path`, as the OpenAPI fixture describes it."""
        self.reads.append((path, dict(query)))
        if self.fail is not None:
            raise MonitoringUnavailableError(self.fail)
        if path in ("/api/v1/devices", "/api/v1/links"):
            rows = self.devices if path == "/api/v1/devices" else self.links
            start = int(query.get("cursor") or 0)
            limit = min(int(query.get("limit") or self.page_size), self.page_size)
            end = start + limit
            return {"items": rows[start:end], "next_cursor": str(end) if end < len(rows) else None}
        if path == "/api/v1/health":
            ids = [i for i in query.get("device_ids", "").split(",") if i]
            return {"items": [{"device_id": i, **self.health[i]} for i in ids if i in self.health]}
        unknown = "monitoring_invalid_answer"
        raise MonitoringUnavailableError(unknown)

    def reads_of(self, path: str) -> int:
        """How many times `path` was read."""
        return sum(1 for p, _ in self.reads if p == path)
