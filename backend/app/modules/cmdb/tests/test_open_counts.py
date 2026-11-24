"""The linked-counts port (REQ-CMDB-009 map badges, REQ-CMDB-019 Associations counters).

work_items answers `{ci: {type: Count(open, total)}}` (lane A, WP-053 S5); the CMDB fills every
LINKED_TYPES slot (a missing CI or type reads as zero), derives the map's open badges from it,
and answers None while no port is registered, never a zero that would read as "nothing open".
"""

import uuid
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pytest

from app.modules.cmdb.service import open_counts
from app.modules.cmdb.service.open_counts import (
    LINKED_TYPES,
    Count,
    OpenCounts,
    counts_for,
    linked_counts_for,
    register_open_counts,
)

CI_A, CI_B = uuid.uuid4(), uuid.uuid4()


class _Fake:
    def __init__(self, answer: Mapping[uuid.UUID, Mapping[str, Count]]) -> None:
        self.answer = answer
        self.asked: list[list[uuid.UUID]] = []

    async def linked_counts(
        self,
        session: Any,  # noqa: ANN401, ARG002 - the port's signature; the fake ignores it
        subject: Any,  # noqa: ANN401, ARG002 - the port's signature; the fake ignores it
        ci_ids: Sequence[uuid.UUID],
    ) -> Mapping[uuid.UUID, Mapping[str, Count]]:
        self.asked.append(list(ci_ids))
        return self.answer


@pytest.fixture(autouse=True)
def _no_port() -> Iterator[None]:
    saved = list(open_counts._PORTS)  # noqa: SLF001 - the registry, restored after each test
    open_counts._PORTS.clear()  # noqa: SLF001
    yield
    open_counts._PORTS[:] = saved  # noqa: SLF001


async def test_with_no_port_both_answers_are_none() -> None:
    assert await counts_for(None, None, [CI_A]) is None  # type: ignore[arg-type]  # the fake needs neither
    assert await linked_counts_for(None, None, [CI_A]) is None  # type: ignore[arg-type]


async def test_every_type_is_filled_and_the_map_badges_come_from_the_open_counts() -> None:
    fake = _Fake(
        {
            CI_A: {
                "incident": Count(open=2, total=5),
                "change": Count(open=1, total=1),
                "release": Count(open=0, total=3),
            }
        }
    )
    register_open_counts(fake)
    linked = await linked_counts_for(None, None, [CI_A, CI_B, CI_A])  # type: ignore[arg-type]
    assert linked is not None
    assert fake.asked == [[CI_A, CI_B]]  # de-duplicated, one call for all CIs
    assert set(linked) == {CI_A, CI_B}
    assert set(linked[CI_A]) == set(LINKED_TYPES)
    assert linked[CI_A]["release"] == Count(open=0, total=3)
    assert linked[CI_A]["service_request"] == Count()  # a type with nothing: zero
    assert linked[CI_B] == {code: Count() for code in LINKED_TYPES}  # a CI with nothing: zero

    badges = await counts_for(None, None, [CI_A, CI_B])  # type: ignore[arg-type]
    assert badges == {
        CI_A: OpenCounts(incident=2, problem=0, change=1),
        CI_B: OpenCounts(),
    }
