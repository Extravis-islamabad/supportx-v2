"""Worker helpers that need no running services (WP-007)."""

import argparse
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import structlog
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from app.modules.system.service.dev_event_log import log_event
from app.shared.events import Actor, ConsumerSpec, EventEnvelope
from conftest import make_settings
from workers import bus
from workers.consumers.runner import RetryPolicy
from workers.events_cli import DeadLetter, build_parser, format_event, parse_since
from workers.heartbeat import instance_id
from workers.metrics import ConsumerMetrics, RelayMetrics, build_meter_provider
from workers.outbox_relay.relay import _describe


def envelope() -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid.uuid4(),
        event_type="identity_access.user.logged_in",
        schema_version=1,
        tenant_id=uuid.UUID(int=7),
        actor=Actor.system("identity_access"),
        occurred_at=datetime(2026, 10, 23, 9, 30, 1, 123000, tzinfo=UTC),
        aggregate_type="user",
        aggregate_id="u-1",
        aggregate_version=4,
        payload={"client": "console"},
    )


def test_retry_policy_backs_off_exponentially_up_to_a_cap() -> None:
    policy = RetryPolicy(max_attempts=5, initial=1.0, maximum=6.0)
    assert [policy.delay(n) for n in range(1, 6)] == [1.0, 2.0, 4.0, 6.0, 6.0]
    assert not policy.exhausted(4)
    assert policy.exhausted(5)


def test_retry_policy_from_settings_with_a_per_consumer_override() -> None:
    async def noop(_e: EventEnvelope, _s: object) -> None:
        return None

    settings = make_settings(consumer_max_attempts=7)
    default = ConsumerSpec(name="x__y", event_types=(">",), handler=noop)
    custom = ConsumerSpec(name="x__z", event_types=(">",), handler=noop, max_attempts=2)
    assert RetryPolicy.from_settings(settings, default).max_attempts == 7
    assert RetryPolicy.from_settings(settings, custom).max_attempts == 2


def test_stream_configs_follow_the_settings() -> None:
    settings = make_settings(
        events_namespace="ns_", events_stream_max_age_hours=2, events_duplicate_window_seconds=60
    )
    names = bus.bus_names(settings)
    events = bus.events_stream_config(names, settings)
    assert events.name == "NS_SUPPORTX_EVENTS"
    assert events.subjects == ["ns_events.>", "ns_replay.>"]
    assert (events.max_age, events.duplicate_window) == (7200.0, 60.0)
    assert bus.dlq_stream_config(names, settings).subjects == ["ns_dlq.>"]


def test_parse_since() -> None:
    assert parse_since(None) is None
    assert parse_since("all") == "all"
    since = parse_since("10m")
    assert isinstance(since, datetime)
    assert timedelta(minutes=9) < datetime.now(UTC) - since < timedelta(minutes=11)
    with pytest.raises(argparse.ArgumentTypeError):
        parse_since("yesterday")


def test_format_event_is_one_readable_line() -> None:
    line = format_event(envelope().to_json())
    assert line.startswith("09:30:01.123  identity_access.user.logged_in")
    assert "user:u-1 v4" in line
    assert "by system:identity_access" in line
    assert '{"client":"console"}' in line
    assert format_event(b"junk").startswith("(not an event envelope")


def test_dead_letter_reads_its_headers() -> None:
    original = envelope()
    letter = DeadLetter(1, "dlq.x", original.to_json(), {"Supportx-Consumer": "x__y"})
    assert letter.consumer == "x__y"
    assert letter.envelope() == original
    assert DeadLetter(2, "dlq.x", b"", {}).consumer == "?"


def test_parser_knows_every_command() -> None:
    parser = build_parser()
    assert parser.parse_args(["dlq-replay", "--seq", "3"]).seq == 3
    assert parser.parse_args(["tail", "--type", "identity_access.>"]).type == "identity_access.>"


def test_metrics_are_observable() -> None:
    reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[reader]).get_meter("test")
    relay, consumers = RelayMetrics(), ConsumerMetrics()
    relay.bind(meter)
    consumers.bind(meter)
    relay.published(10, duplicates=2)
    relay.failed(1)
    relay.oldest_unpublished_age_seconds = 3.5
    ConsumerMetrics.bump(consumers.processed, "a__b")
    consumers.lag["a__b"] = 4
    consumers.dlq_messages = 2
    data = reader.get_metrics_data()
    assert data is not None
    names = {
        metric.name
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }
    assert {
        "supportx.relay.published_events",
        "supportx.relay.publish_failures",
        "supportx.outbox.oldest_unpublished_age",
        "supportx.consumer.lag",
        "supportx.dlq.messages",
        "supportx.consumer.processed_events",
    } <= names
    assert relay.snapshot()["duplicates_total"] == 2
    assert consumers.snapshot()["lag"] == {"a__b": 4}
    assert build_meter_provider(make_settings(metrics_exporter="console")) is not None


def test_relay_error_text_is_one_short_line() -> None:
    assert _describe(TimeoutError()) == "TimeoutError"
    assert _describe(RuntimeError("a\nb  c")) == "RuntimeError: a b c"


def test_instance_ids_are_safe_kv_tokens() -> None:
    value = instance_id()
    assert all(ch.isalnum() or ch in "-_" for ch in value)


async def test_dev_logger_logs_one_line_per_event() -> None:
    with structlog.testing.capture_logs() as logs:
        await log_event(envelope(), None)
    (entry,) = logs
    assert entry["event"] == "event_received"
    assert entry["event_type"] == "identity_access.user.logged_in"
    assert entry["aggregate"] == "user:u-1"
