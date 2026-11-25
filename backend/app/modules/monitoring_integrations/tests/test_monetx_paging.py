"""The MonetX client's paging is bounded (lane C's #640 review): no answer exhausts the worker."""

from collections.abc import Mapping
from typing import Any

import pytest

from app.modules.monitoring_integrations.domain.monitoring import INVALID_ANSWER, TOO_LARGE
from app.modules.monitoring_integrations.infra.monetx_client import (
    MAX_ITEMS,
    PAGE,
    MonetXClient,
    MonitoringUnavailableError,
)


class _Endless:
    """A MonetX that always has one more page (and, if asked, ignores `limit`)."""

    def __init__(self, per_page: int = PAGE, *, junk: bool = False) -> None:
        self.per_page, self.junk, self.reads = per_page, junk, 0

    async def read(self, path: str, query: Mapping[str, str]) -> Any:  # noqa: ANN401 - JSON
        del path, query
        self.reads += 1
        item: Any = "junk" if self.junk else {"id": f"d{self.reads}", "name": "x"}
        return {"items": [item] * self.per_page, "next_cursor": f"c{self.reads}"}


class _SameCursor:
    async def read(self, path: str, query: Mapping[str, str]) -> Any:  # noqa: ANN401 - JSON
        del path, query
        return {"items": [{"id": "d", "name": "x"}], "next_cursor": "again"}


@pytest.mark.parametrize(
    "transport",
    [_Endless(), _Endless(per_page=MAX_ITEMS + 1), _Endless(junk=True)],
    ids=["never-stops", "ignores-limit", "unreadable-items"],
)
async def test_a_monetx_that_never_stops_is_refused_as_too_large(transport: _Endless) -> None:
    with pytest.raises(MonitoringUnavailableError) as refused:
        await MonetXClient(transport).devices()
    assert refused.value.code == TOO_LARGE
    assert transport.reads <= MAX_ITEMS // PAGE + 1  # bounded, never endless


async def test_a_repeated_cursor_is_an_invalid_answer() -> None:
    with pytest.raises(MonitoringUnavailableError) as refused:
        await MonetXClient(_SameCursor()).links()
    assert refused.value.code == INVALID_ANSWER
