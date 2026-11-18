"""Export formats offered only when they can be made (QA6-RPT-01). No Valkey needed.

These tests also run inside the PDF worker image, which has no backend/conftest.py, so they build
their settings here (never `from conftest import ...`).
"""

import asyncio

import pytest

from app.core.config import Settings
from app.modules.analytics.service import capabilities

DOWN = "unreachable"


def make_settings(**overrides: object) -> Settings:
    """Test settings with no Valkey, never read from an environment file."""
    return Settings(_env_file=None, profile="test", tracing_enabled=False, **overrides)  # type: ignore[call-arg, arg-type]  # pydantic-settings' init keyword, validated values


def _renderer() -> object:
    return object()


async def test_qa6_rpt_01_no_pdf_without_a_pdf_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capabilities, "_pdf_renderer", lambda: None)
    settings = make_settings(valkey_url=None)
    assert await capabilities.export_formats(settings) == ["xlsx", "csv"]


async def test_qa6_rpt_01_pdf_when_this_process_renders_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capabilities, "_pdf_renderer", _renderer)
    settings = make_settings(valkey_url=None)
    assert await capabilities.export_formats(settings) == ["xlsx", "csv", "pdf"]


async def test_qa6_rpt_01_the_heartbeat_lapses_when_valkey_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Down:
        async def exists(self, _key: str) -> int:
            raise OSError(DOWN)

    settings = make_settings(valkey_url=None)
    monkeypatch.setattr(capabilities, "_valkey", lambda _settings: Down())
    assert await capabilities.export_formats(settings) == ["xlsx", "csv"]


async def test_a_client_from_another_loop_never_errors_and_offers_only_the_always_formats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The flake that dropped #524 and #525: a client bound to a closed loop raised RuntimeError,
    which escaped as a 500. Now: fail closed, Excel and CSV only, never the gated PDF."""

    class OtherLoop:
        async def exists(self, _key: str) -> int:
            raise RuntimeError(DOWN)  # "Future attached to a different loop"

    settings = make_settings(valkey_url=None)
    monkeypatch.setattr(capabilities, "_pdf_renderer", _renderer)
    monkeypatch.setattr(capabilities, "_valkey", lambda _settings: OtherLoop())
    assert await capabilities.export_formats(settings) == ["xlsx", "csv"]


def test_each_event_loop_gets_its_own_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """A new running loop makes a new client; the same loop reuses its own."""
    made: list[asyncio.AbstractEventLoop] = []

    def fake_client(_settings: object) -> object:
        made.append(asyncio.get_running_loop())
        return object()

    monkeypatch.setattr(capabilities, "client", fake_client)
    monkeypatch.setattr(capabilities, "_clients", {})
    settings = make_settings(valkey_url=None)

    async def twice() -> tuple[object, object]:
        return capabilities._valkey(settings), capabilities._valkey(settings)  # noqa: SLF001

    first = asyncio.run(twice())
    second = asyncio.run(twice())
    assert first[0] is first[1]  # one client per loop
    assert second[0] is not first[0]  # a new loop, a new client
    assert len(made) == 2
    assert made[0] is not made[1]
