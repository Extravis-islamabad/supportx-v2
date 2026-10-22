import io
import json
import logging
from collections.abc import Callable, Iterator

import pytest
import structlog
from opentelemetry.sdk.trace import TracerProvider

from app.core.config import Settings
from app.core.logging import REDACTED, configure_logging, get_logger, redact
from app.core.request_context import bind_request, clear_request


@pytest.fixture
def json_logs(
    settings_factory: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> Iterator[io.StringIO]:
    """Configure JSON logging into a buffer; return the buffer."""
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stderr", buffer)
    configure_logging(settings_factory(log_format="json"))
    yield buffer
    clear_request()
    configure_logging(settings_factory())


def lines(buffer: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]


def test_redact_masks_sensitive_keys_recursively() -> None:
    event = {
        "user": "u1",
        "password": "hunter2",
        "headers": {"Authorization": "Bearer abc", "X-Api-Key": "k", "accept": "json"},
        "items": [{"client_secret": "s"}, ("ok",)],
        "contact_email": "a@b.co",
        "count": 3,
    }
    assert redact(event) == {
        "user": "u1",
        "password": REDACTED,
        "headers": {"Authorization": REDACTED, "X-Api-Key": REDACTED, "accept": "json"},
        "items": [{"client_secret": REDACTED}, ("ok",)],
        "contact_email": REDACTED,
        "count": 3,
    }


def test_redact_scrubs_credentials_and_emails_inside_strings() -> None:
    text = "connect postgresql://app:hunter2@db:5432/x failed for jane.doe@example.com"
    assert redact(text) == (f"connect postgresql://{REDACTED}@db:5432/x failed for {REDACTED}")


def test_json_lines_carry_request_and_tenant_ids(json_logs: io.StringIO) -> None:
    log = get_logger("test")
    log.info("outside_request")
    bind_request("req-1")
    log.info("inside_request", password="hunter2", dsn="valkey://:pw@kv:6379/0")
    logging.getLogger("uvicorn.error").warning("from stdlib")

    outside, inside, stdlib = lines(json_logs)
    assert outside["request_id"] is None
    assert outside["tenant_id"] is None
    assert inside["request_id"] == "req-1"
    assert inside["password"] == REDACTED
    assert inside["dsn"] == f"valkey://{REDACTED}@kv:6379/0"
    assert inside["level"] == "info"
    assert "timestamp" in inside
    assert stdlib["event"] == "from stdlib"
    assert stdlib["request_id"] == "req-1"
    assert "hunter2" not in json_logs.getvalue()


def test_log_lines_include_trace_context(json_logs: io.StringIO) -> None:
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("work") as span:
        get_logger("test").info("traced")
    (line,) = lines(json_logs)
    assert line["trace_id"] == format(span.get_span_context().trace_id, "032x")
    assert len(str(line["span_id"])) == 16


def test_exceptions_are_rendered_server_side(json_logs: io.StringIO) -> None:
    try:
        msg = "boom"
        raise ValueError(msg)  # noqa: TRY301 - raising inside try is the scenario under test
    except ValueError:
        get_logger("test").exception("failed")
    (line,) = lines(json_logs)
    assert "ValueError: boom" in str(line["exception"])


def test_console_format_is_human_readable(
    settings_factory: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stderr", buffer)
    configure_logging(settings_factory(log_format="console"))
    structlog.contextvars.bind_contextvars(request_id="r-9")
    get_logger("test").info("hello")
    structlog.contextvars.clear_contextvars()
    output = buffer.getvalue()
    assert "hello" in output
    assert "request_id=r-9" in output
    assert not output.lstrip().startswith("{")
