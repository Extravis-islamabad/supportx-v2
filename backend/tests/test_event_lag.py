"""Event lag per hop (rule c): a warning when slow, a histogram always; IDs and types only."""

from datetime import timedelta

import structlog
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import HistogramDataPoint, InMemoryMetricReader

from tests.test_workers_units import envelope
from workers.event_lag import SLOW_AFTER_SECONDS, note_lag
from workers.metrics import ConsumerMetrics


def test_a_slow_event_is_logged_with_ids_and_types_and_never_its_payload() -> None:
    event = envelope()
    with structlog.testing.capture_logs() as logs:
        quick = note_lag("consumer", "c__one", event, event.occurred_at + timedelta(seconds=0.5))
        slow = note_lag(
            "fanout", "realtime__fanout", event, event.occurred_at + timedelta(seconds=8)
        )
    assert (quick, slow) == (0.5, 8.0)
    warned = [entry for entry in logs if entry["event"] == "event_lag"]
    assert len(warned) == 1  # only the one over SLOW_AFTER_SECONDS
    assert SLOW_AFTER_SECONDS < 8
    entry = warned[0]
    assert {k: entry[k] for k in ("stage", "consumer", "event_type", "lag_ms")} == {
        "stage": "fanout",
        "consumer": "realtime__fanout",
        "event_type": "identity_access.user.logged_in",
        "lag_ms": 8000,
    }
    assert entry["event_id"] == str(event.event_id)
    assert "payload" not in entry  # never the payload ...
    assert "console" not in str(entry)  # ... nor any of its values


def test_the_lag_histogram_records_by_stage_and_consumer() -> None:
    reader = InMemoryMetricReader()
    metrics = ConsumerMetrics()
    metrics.bind(MeterProvider(metric_readers=[reader]).get_meter("test"))
    metrics.event_lag("consumer", "c__one", 0.4)
    metrics.event_lag("fanout", "realtime__fanout", 8.0)
    data = reader.get_metrics_data()
    assert data is not None
    lag = next(
        metric
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == "supportx.event.lag"
    )
    assert lag.unit == "s"
    histogram = [p for p in lag.data.data_points if isinstance(p, HistogramDataPoint)]
    points = {
        (dict(p.attributes or {})["stage"], dict(p.attributes or {})["consumer"]): (p.count, p.sum)
        for p in histogram
    }
    assert points == {("consumer", "c__one"): (1, 0.4), ("fanout", "realtime__fanout"): (1, 8.0)}
