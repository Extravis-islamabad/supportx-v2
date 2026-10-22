"""Worker metrics with OpenTelemetry (architecture.md §15; WP-007).

Instruments are named the OpenTelemetry way; a Prometheus exporter turns them into
`supportx_outbox_oldest_unpublished_age_seconds`, `supportx_relay_published_events_total`,
`supportx_consumer_lag`, `supportx_dlq_messages` and so on. Exporting is off by default
(`SUPPORTX_METRICS_EXPORTER=none`); `console` prints them every 15 s. The Prometheus scrape
endpoint arrives with the deployment work (WP-014). The same numbers are in every heartbeat, so
`make events-stats` and /ready show them today.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from opentelemetry.metrics import CallbackOptions, Counter, Meter, Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

from app import __version__
from app.core.config import Settings

METER_NAME = "supportx.events"


def build_meter_provider(settings: Settings) -> MeterProvider:
    """Meter provider for one worker process, exporting only if an exporter is configured."""
    readers = (
        [PeriodicExportingMetricReader(ConsoleMetricExporter(), export_interval_millis=15_000)]
        if settings.metrics_exporter == "console"
        else []
    )
    return MeterProvider(
        metric_readers=readers,
        resource=Resource.create(
            {"service.name": settings.service_name, "service.version": __version__}
        ),
    )


@dataclass
class RelayMetrics:
    """What the relay reports."""

    published_total: int = 0
    duplicates_total: int = 0
    failed_total: int = 0
    purged_total: int = 0
    oldest_unpublished_age_seconds: float = 0.0
    _published: Counter | None = field(default=None, init=False, repr=False)
    _failed: Counter | None = field(default=None, init=False, repr=False)

    def bind(self, meter: Meter) -> None:
        """Register the instruments (observable ones read the fields above)."""
        self._published = meter.create_counter(
            "supportx.relay.published_events", unit="{event}", description="Events published"
        )
        self._failed = meter.create_counter(
            "supportx.relay.publish_failures", unit="{event}", description="Failed publishes"
        )
        meter.create_observable_gauge(
            "supportx.outbox.oldest_unpublished_age",
            callbacks=[self._observe_age],
            unit="s",
            description="Age of the oldest event still waiting in the outbox (0 = none)",
        )

    def _observe_age(self, _options: CallbackOptions) -> Iterable[Observation]:
        yield Observation(self.oldest_unpublished_age_seconds)

    def published(self, count: int, duplicates: int) -> None:
        """A batch was acknowledged by JetStream."""
        self.published_total += count
        self.duplicates_total += duplicates
        if count and self._published is not None:
            self._published.add(count)

    def failed(self, count: int) -> None:
        """Publishing failed for `count` events (they stay in the outbox)."""
        self.failed_total += count
        if count and self._failed is not None:
            self._failed.add(count)

    def snapshot(self) -> dict[str, float | int]:
        """For the heartbeat."""
        return {
            "published_total": self.published_total,
            "duplicates_total": self.duplicates_total,
            "failed_total": self.failed_total,
            "purged_total": self.purged_total,
            "oldest_unpublished_age_seconds": round(self.oldest_unpublished_age_seconds, 3),
        }


@dataclass
class ConsumerMetrics:
    """What the consumer worker reports, per consumer."""

    processed: dict[str, int] = field(default_factory=dict)
    duplicates: dict[str, int] = field(default_factory=dict)
    retried: dict[str, int] = field(default_factory=dict)
    dead_lettered: dict[str, int] = field(default_factory=dict)
    lag: dict[str, int] = field(default_factory=dict)
    dlq_messages: int = 0

    def bind(self, meter: Meter) -> None:
        """Register the observable instruments."""
        meter.create_observable_gauge(
            "supportx.consumer.lag",
            callbacks=[self._observe_lag],
            unit="{message}",
            description="Messages not yet acknowledged by the consumer (pending + in flight)",
        )
        meter.create_observable_gauge(
            "supportx.dlq.messages",
            callbacks=[self._observe_dlq],
            unit="{message}",
            description="Messages in the dead-letter stream",
        )
        meter.create_observable_counter(
            "supportx.consumer.processed_events",
            callbacks=[self._observe_processed],
            unit="{event}",
        )

    def _observe_lag(self, _options: CallbackOptions) -> Iterable[Observation]:
        for name, value in self.lag.items():
            yield Observation(value, {"consumer": name})

    def _observe_dlq(self, _options: CallbackOptions) -> Iterable[Observation]:
        yield Observation(self.dlq_messages)

    def _observe_processed(self, _options: CallbackOptions) -> Iterable[Observation]:
        for name, value in self.processed.items():
            yield Observation(value, {"consumer": name})

    @staticmethod
    def bump(counter: dict[str, int], consumer: str) -> None:
        """Add one to a per-consumer counter."""
        counter[consumer] = counter.get(consumer, 0) + 1

    def snapshot(self) -> dict[str, object]:
        """For the heartbeat."""
        return {
            "processed": dict(self.processed),
            "duplicates_skipped": dict(self.duplicates),
            "retried": dict(self.retried),
            "dead_lettered": dict(self.dead_lettered),
            "lag": dict(self.lag),
            "dlq_messages": self.dlq_messages,
        }
