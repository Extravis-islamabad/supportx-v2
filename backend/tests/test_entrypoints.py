import json
from pathlib import Path
from typing import Any

import pytest

import app.__main__ as entry
from app.core.config import get_settings
from tooling import export_openapi


def test_python_dash_m_app_runs_uvicorn_with_the_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setenv("SUPPORTX_HTTP_PORT", "8123")
    get_settings.cache_clear()
    try:
        entry.main()
    finally:
        get_settings.cache_clear()

    (args, kwargs), *_ = calls
    assert args == ("app.main:create_app",)
    assert kwargs["factory"] is True
    assert kwargs["port"] == 8123
    assert kwargs["access_log"] is False


def test_openapi_export_writes_and_checks(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"
    assert export_openapi.main(["--check", str(target)]) == 1
    assert export_openapi.main([str(target)]) == 0
    schema = json.loads(target.read_text())
    assert schema["openapi"].startswith("3.1")
    assert "/api/v1/ready" in schema["paths"]
    assert "ProblemDetail" in schema["components"]["schemas"]
    assert export_openapi.main(["--check", str(target)]) == 0
    target.write_text("{}\n")
    assert export_openapi.main(["--check", str(target)]) == 1
    assert export_openapi.main([]) == 2


def test_committed_openapi_matches_the_code() -> None:
    committed = Path(__file__).resolve().parents[2] / "frontend/packages/api-client/openapi.json"
    assert export_openapi.main(["--check", str(committed)]) == 0
