"""Export formats offered only when they can be made (QA6-RPT-01). No Valkey needed."""

import pytest

from app.modules.analytics.service import capabilities
from conftest import make_settings

DOWN = "unreachable"


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
