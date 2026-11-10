"""Problems as a report source with their own figures (WP-044c D15)."""

import pytest

from tests.db.test_incidents_api import CONSOLE, World, world

pytestmark = pytest.mark.db

__all__ = ["world"]  # the fixture, re-used


def test_d15_the_problem_source_offers_its_own_figures() -> None:
    """Problems' type, root cause category (never its text), known error and acceptance."""
    from app.modules.work_items.domain.types import PROBLEM  # noqa: PLC0415 - this test only
    from app.modules.work_items.service.reporting import (  # noqa: PLC0415 - this test only
        PROBLEM_DIMENSIONS,
        WorkItemSource,
    )

    source = WorkItemSource(PROBLEM)
    assert source.entity == "problem"
    assert set(PROBLEM_DIMENSIONS) == {
        "problem_type",
        "root_cause_category",
        "known_error_at",
        "accepted_at",
    }
    assert "root_cause" not in PROBLEM_DIMENSIONS  # D-140 Q7: the text is never a figure


async def test_d15_incident_reports_never_offer_the_problems_fields(world: World) -> None:
    a = world.a
    response = await world.call(
        "POST",
        "/reports/run",
        a,
        a.admin,
        json={"definition": {"entity": "incident", "group_by": [{"field": "problem_type"}]}},
        headers=CONSOLE,
    )
    assert response.status_code == 422, response.text
