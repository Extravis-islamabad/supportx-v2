"""The reporting port's registry (WP-035, ADR-033)."""

from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.reporting import (
    ReportingSource,
    UnknownEntityError,
    provider_for,
    register_source,
    registered_entities,
    unregister_source,
)


@dataclass(frozen=True)
class _Provider:
    entity: str = "widget_test"
    feature: str = "incident"
    permission: str = "incidents.view"

    async def source(self, session: AsyncSession, subject: Any) -> ReportingSource:  # noqa: ANN401 - port signature
        raise NotImplementedError


def test_a_registered_entity_is_found_and_unregistering_removes_it() -> None:
    provider = _Provider()
    register_source(provider)
    try:
        assert provider_for("widget_test") is provider
        assert "widget_test" in registered_entities()
    finally:
        unregister_source("widget_test")
    assert "widget_test" not in registered_entities()


def test_an_unknown_entity_raises() -> None:
    with pytest.raises(UnknownEntityError):
        provider_for("no_such_entity")
