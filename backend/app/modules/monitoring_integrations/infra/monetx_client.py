"""The MonetX client: the module's only way out, and it only ever reads (ADR-017, D-001).

**GET only, by construction.** The one method this module names is `GET` (`_READ`); there's no
write call, no write verb and no request body. `tests/test_monetx_contract.py` reads this file
and fails if that ever changes (the coordinator's S6 condition 1).

Every call goes through `app/shared/egress` (ADR-043 §8): the address checked and pinned, TLS
verified, no redirects followed, a 10 s limit. The API token travels only as a secret header,
which egress never logs or returns. MonetX's API has no docs yet (D-172), so the paths and fields
below are our assumption, written down in `tests/fixtures/monetx-openapi.yaml`, and the
`FakeMonetX` serves exactly that.
"""

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import urlencode

from app.modules.monitoring_integrations.domain.monitoring import (
    INVALID_ANSWER,
    NOT_REACHABLE_FROM_SAAS,
    REFUSED,
    UNREACHABLE,
)
from app.shared.egress import Allowance, Destination, EgressError, OutboundRequest, send

_READ = "GET"  # the only method this module ever sends
_HTTP_REFUSED = frozenset({401, 403})
PAGE = 500


class MonitoringUnavailableError(Exception):
    """MonetX couldn't be read; `code` is a labelled reason, never MonetX's own text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Device:
    """A MonetX device, as the topology import uses it."""

    id: str
    name: str
    kind: str
    group: str | None


@dataclass(frozen=True)
class Link:
    """A MonetX link between two devices."""

    id: str
    from_id: str
    to_id: str


@dataclass(frozen=True)
class DeviceHealth:
    """One device's health as MonetX reports it (its own status word, mapped by the domain)."""

    status: str
    since: datetime | None
    problem_count: int


class MonetXTransport(Protocol):
    """Reads one MonetX path: the decoded JSON, or `MonitoringUnavailableError`."""

    async def read(self, path: str, query: Mapping[str, str]) -> Any:  # noqa: ANN401 - JSON
        """GET `path` with `query`."""
        ...


class EgressTransport:
    """MonetX over `app/shared/egress`: the real transport."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        allowance: Allowance,
        tenant_id: uuid.UUID,
        destination: Destination | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._allowance = allowance
        self._tenant = tenant_id
        self._destination = destination

    async def read(self, path: str, query: Mapping[str, str]) -> Any:  # noqa: ANN401 - JSON
        """One guarded read; the token only as a secret header."""
        url = f"{self._base}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        request = OutboundRequest(
            method=_READ,
            url=url,
            headers={"Accept": "application/json"},
            secret_headers={"Authorization": f"Bearer {self._token}"},
        )
        try:
            response = await send(
                request,
                allowance=self._allowance,
                module="monitoring_integrations",
                tenant_id=self._tenant,
                destination=self._destination,
            )
        except EgressError as error:
            raise MonitoringUnavailableError(_reason(error)) from None
        try:
            return json.loads(response.body)
        except ValueError:
            raise MonitoringUnavailableError(INVALID_ANSWER) from None


def _reason(error: EgressError) -> str:
    """Egress's code as ours (a labelled reason, never MonetX's text).

    `blocked` is an address this installation may not reach. On SaaS that's a private MonetX,
    which waits for the relay (D-172).
    """
    if error.code == "blocked":
        return NOT_REACHABLE_FROM_SAAS
    if error.status in _HTTP_REFUSED:
        return REFUSED
    return UNREACHABLE


def _text(value: object, field: str) -> str:
    if not isinstance(value, str | int) or str(value) == "":
        raise MonitoringUnavailableError(INVALID_ANSWER) from ValueError(field)
    return str(value)


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class MonetXClient:
    """What S6 reads: devices, links and health. Pages through cursors; never writes."""

    def __init__(self, transport: MonetXTransport) -> None:
        self._transport = transport

    async def _pages(self, path: str) -> list[Mapping[str, Any]]:
        items: list[Mapping[str, Any]] = []
        cursor: str | None = None
        for _ in range(1000):  # a bound: 500k items at most, never an endless loop
            query = {"limit": str(PAGE), **({"cursor": cursor} if cursor else {})}
            page = await self._transport.read(path, query)
            if not isinstance(page, Mapping) or not isinstance(page.get("items"), list):
                raise MonitoringUnavailableError(INVALID_ANSWER)
            items.extend(i for i in page["items"] if isinstance(i, Mapping))
            nxt = page.get("next_cursor")
            if not isinstance(nxt, str) or not nxt:
                return items
            cursor = nxt
        raise MonitoringUnavailableError(INVALID_ANSWER)

    async def check(self) -> None:
        """A connection test: one small read."""
        await self._transport.read("/api/v1/devices", {"limit": "1"})

    async def devices(self) -> list[Device]:
        """Every device MonetX reports for this connection."""
        return [
            Device(
                id=_text(item.get("id"), "id"),
                name=_text(item.get("name") or item.get("id"), "name")[:200],
                kind=str(item.get("kind") or ""),
                group=str(item["group"]) if item.get("group") not in (None, "") else None,
            )
            for item in await self._pages("/api/v1/devices")
        ]

    async def links(self) -> list[Link]:
        """Every link between two devices."""
        return [
            Link(
                id=_text(item.get("id"), "id"),
                from_id=_text(item.get("from"), "from"),
                to_id=_text(item.get("to"), "to"),
            )
            for item in await self._pages("/api/v1/links")
        ]

    async def health(self, device_ids: Sequence[str]) -> dict[str, DeviceHealth]:
        """Health of these devices; a device MonetX doesn't report is left out."""
        if not device_ids:
            return {}
        page = await self._transport.read("/api/v1/health", {"device_ids": ",".join(device_ids)})
        if not isinstance(page, Mapping) or not isinstance(page.get("items"), list):
            raise MonitoringUnavailableError(INVALID_ANSWER)
        found: dict[str, DeviceHealth] = {}
        for item in page["items"]:
            if not isinstance(item, Mapping) or item.get("device_id") is None:
                continue
            count = item.get("problem_count")
            found[str(item["device_id"])] = DeviceHealth(
                status=str(item.get("status") or ""),
                since=_when(item.get("since")),
                problem_count=count if isinstance(count, int) and count >= 0 else 0,
            )
        return found
