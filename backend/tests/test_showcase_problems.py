"""The showcase's problems converge on a re-run (QA9-F-02): no duplicate, no clashing link."""

import asyncio
import uuid
from collections.abc import Mapping
from typing import Any

from tooling import showcase_lane_a as lane_a


class FakeApi:
    """The problem endpoints the seed calls, with the server's one rule: one problem each."""

    def __init__(self) -> None:
        self.problems: dict[str, dict[str, Any]] = {}
        self.caused_by: dict[str, str] = {}  # incident -> problem
        self.calls: list[tuple[str, str]] = []

    async def call(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,  # noqa: ANN401 - request bodies
        params: Mapping[str, Any] | None = None,
        idempotency: str | None = None,
        version: int | None = None,
    ) -> Any:  # noqa: ANN401 - the endpoint's JSON
        del params, idempotency, version
        self.calls.append((method, path))
        if (method, path) == ("POST", "/api/v1/problems"):
            pid = str(uuid.uuid4())
            self.problems[pid] = {
                "id": pid,
                "subject": json["subject"],
                "known_error_at": None,
                "version": 1,
            }
            return self.problems[pid]
        if path == "/api/v1/problems/from-incidents/preview":
            ids = json["incident_ids"]
            return {
                "already_caused": [
                    {"incident_id": i, "problem_display_id": "PRB-1"}
                    for i in ids
                    if i in self.caused_by
                ]
            }
        pid = path.split("/")[4]
        if path.endswith("/incidents"):
            assert json["incident_id"] not in self.caused_by, "incident_has_problem (409)"
            self.caused_by[json["incident_id"]] = pid
            return {}
        if path.endswith("/known-error"):
            assert self.problems[pid]["known_error_at"] is None, "already a known error"
            self.problems[pid]["known_error_at"] = "2026-11-09T00:00:00Z"
            return {}
        return self.problems[pid]

    async def all_pages(self, path: str, params: Mapping[str, Any] | None = None) -> list[Any]:
        del params
        assert path == "/api/v1/problems"
        return list(self.problems.values())

    def as_user(self, user: uuid.UUID) -> "FakeApi":
        del user
        return self


INCIDENTS = [{"id": f"i{n}", "display_id": f"INC-{n}"} for n in range(1, 11)]


def test_a_rerun_after_a_half_run_and_a_new_order_makes_no_duplicate() -> None:
    api = FakeApi()
    # The first run stopped after the first problem; since then the list's order changed.
    first = lane_a.PROBLEMS[0]
    api.problems["p1"] = {"id": "p1", "subject": first[0], "known_error_at": None, "version": 1}
    api.caused_by |= {"i1": "p1", "i2": "p1"}
    made = asyncio.run(lane_a.ensure_problems(api, "owner", list(reversed(INCIDENTS))))
    assert made == len(lane_a.PROBLEMS) - 1
    assert sorted(p["subject"] for p in api.problems.values()) == sorted(
        p[0] for p in lane_a.PROBLEMS
    )
    # Each problem has its own two incidents, by display number; the half-run one is finished.
    assert api.caused_by == {
        "i1": "p1",
        "i2": "p1",
        **{f"i{n}": pid for pid, ns in _made(api) for n in ns},
    }
    assert api.problems["p1"]["known_error_at"] is not None

    # Run again: nothing more.
    before, seen = dict(api.caused_by), len(api.calls)
    assert asyncio.run(lane_a.ensure_problems(api, "owner", INCIDENTS)) == 0
    assert api.caused_by == before
    assert not [c for c in api.calls[seen:] if c[1].endswith(("/incidents", "/known-error"))]


def _made(api: FakeApi) -> list[tuple[str, tuple[int, ...]]]:
    by_subject = {p["subject"]: pid for pid, p in api.problems.items()}
    later = range(1, len(lane_a.PROBLEMS))
    return [(by_subject[lane_a.PROBLEMS[n][0]], (n * 2 + 1, n * 2 + 2)) for n in later]
