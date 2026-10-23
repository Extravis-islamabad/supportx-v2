"""Event envelope, registry, subjects and consumer declarations: pure logic, no I/O (WP-007)."""

import uuid
from datetime import UTC, datetime
from typing import ClassVar

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.modules import ModuleSpec, discover_modules
from app.shared.events import (
    Actor,
    BusNames,
    ConsumerSpec,
    DomainEvent,
    EventEnvelope,
    EventRegistry,
    UnregisteredEventError,
    active_registry,
)
from app.shared.events import registry as registry_module
from app.shared.events.consumers import (
    ConsumerRegistrationError,
    consumers_from_modules,
    validate_consumer,
)
from app.shared.events.registry import EventRegistrationError


class TicketAssigned(DomainEvent):
    event_type: ClassVar[str] = "work_items.ticket.assigned"
    aggregate_type: ClassVar[str] = "ticket"

    ticket_id: uuid.UUID


class TicketAssignedV2(DomainEvent):
    event_type: ClassVar[str] = "work_items.ticket.assigned"
    schema_version: ClassVar[int] = 2
    aggregate_type: ClassVar[str] = "ticket"

    ticket_id: uuid.UUID
    assignee_id: uuid.UUID


def registry_with(*events: type, module: str = "work_items") -> EventRegistry:
    registry = EventRegistry()
    for event in events:
        registry.register(event, module=module)
    return registry


def envelope(**overrides: object) -> EventEnvelope:
    values: dict[str, object] = {
        "event_id": uuid.uuid4(),
        "event_type": "work_items.ticket.assigned",
        "schema_version": 1,
        "tenant_id": uuid.uuid4(),
        "actor": Actor.system("work_items"),
        "occurred_at": datetime.now(UTC),
        "aggregate_type": "ticket",
        "aggregate_id": "t-1",
        "payload": {"ticket_id": str(uuid.uuid4())},
    }
    return EventEnvelope.model_validate({**values, **overrides})


# --- registry ------------------------------------------------------------------------------------


def test_versions_of_one_type_live_side_by_side() -> None:
    registry = registry_with(TicketAssigned, TicketAssignedV2)
    assert registry.model_for("work_items.ticket.assigned", 1) is TicketAssigned
    assert registry.model_for("work_items.ticket.assigned", 2) is TicketAssignedV2
    assert registry.event_types() == {"work_items.ticket.assigned"}
    assert [key for key, _ in registry] == [
        ("work_items.ticket.assigned", 1),
        ("work_items.ticket.assigned", 2),
    ]
    registry.register(TicketAssigned, module="work_items")  # same class again: harmless


def test_a_module_cannot_publish_in_another_modules_name() -> None:
    with pytest.raises(EventRegistrationError, match="must start with 'sla'"):
        registry_with(TicketAssigned, module="sla")


@pytest.mark.parametrize(
    ("event_type", "aggregate_type", "version", "message"),
    [
        ("work_items.ticket", "ticket", 1, "<module>.<entity>.<action>"),
        ("work_items.Ticket.assigned", "ticket", 1, "<module>.<entity>.<action>"),
        ("work_items.ticket.assigned.now", "ticket", 1, "<module>.<entity>.<action>"),
        ("work_items.ticket.assigned", "Ticket", 1, "aggregate_type"),
        ("work_items.ticket.assigned", "ticket", 0, "schema_version"),
    ],
)
def test_naming_and_versioning_rules(
    event_type: str, aggregate_type: str, version: int, message: str
) -> None:
    bad = type(
        "Bad",
        (DomainEvent,),
        {
            "event_type": event_type,
            "aggregate_type": aggregate_type,
            "schema_version": version,
            "__annotations__": {},
        },
    )
    with pytest.raises(EventRegistrationError, match=message):
        registry_with(bad)


def test_two_classes_cannot_claim_the_same_version() -> None:
    class Impostor(DomainEvent):
        event_type: ClassVar[str] = "work_items.ticket.assigned"
        aggregate_type: ClassVar[str] = "ticket"

    with pytest.raises(EventRegistrationError, match="declared twice"):
        registry_with(TicketAssigned, Impostor)


def test_only_domain_events_register() -> None:
    with pytest.raises(EventRegistrationError, match="not a DomainEvent"):
        registry_with(dict)


def test_require_and_parse() -> None:
    registry = registry_with(TicketAssigned)
    registry.require(TicketAssigned(ticket_id=uuid.uuid4()))
    with pytest.raises(UnregisteredEventError):
        registry.require(TicketAssignedV2(ticket_id=uuid.uuid4(), assignee_id=uuid.uuid4()))
    ticket = uuid.uuid4()
    parsed = registry.parse(envelope(payload={"ticket_id": str(ticket), "added_later": 1}))
    assert parsed == TicketAssigned(ticket_id=ticket)  # unknown fields are ignored
    with pytest.raises(UnregisteredEventError):
        registry.parse(envelope(schema_version=9))


def test_registry_from_modules_and_the_lazy_default(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = EventRegistry.from_modules([ModuleSpec(name="work_items", events=[TicketAssigned])])
    assert registry.event_types() == {"work_items.ticket.assigned"}
    monkeypatch.setattr(registry_module, "_active", None)
    assert "identity_access.user.logged_in" in active_registry().event_types()


def test_every_app_module_event_follows_the_rules() -> None:
    registry = EventRegistry.from_modules(discover_modules())
    assert {
        "identity_access.user.provisioned",
        "identity_access.user.updated",
        "identity_access.user.logged_in",
        "identity_access.user.logged_out",
        "identity_access.session.tenant_switched",
    } <= registry.event_types()


# --- envelope ------------------------------------------------------------------------------------


def test_envelope_round_trips_and_ignores_unknown_fields() -> None:
    original = envelope(aggregate_version=3, correlation_id="req-1")
    assert EventEnvelope.from_json(original.to_json()) == original
    widened = original.to_json().replace(b'"payload"', b'"future_field":1,"payload"')
    assert EventEnvelope.from_json(widened) == original


def test_envelope_rejects_bad_types() -> None:
    with pytest.raises(ValidationError):
        envelope(event_type="NotAType")
    with pytest.raises(ValidationError):
        EventEnvelope.from_json(b"{}")


def test_actor_helpers() -> None:
    user = uuid.uuid4()
    assert Actor.user(user).model_dump() == {"type": "user", "id": str(user)}
    assert Actor.system("workflow").model_dump() == {"type": "system", "id": "workflow"}


# --- subjects ------------------------------------------------------------------------------------


def test_subjects_put_the_tenant_first() -> None:
    names = BusNames()
    tenant = uuid.uuid4()
    assert names.event_subject(tenant, "work_items.ticket.assigned") == (
        f"events.{tenant}.work_items.ticket.assigned"
    )
    assert names.event_filter(">") == "events.>"
    assert names.event_filter("work_items.>") == "events.*.work_items.>"
    assert names.replay_subject("search__index", tenant, "a.b.c") == (
        f"replay.search__index.{tenant}.a.b.c"
    )
    assert names.replay_filter("search__index") == "replay.search__index.>"
    assert (
        names.dlq_subject("search__index", tenant, "a.b.c") == f"dlq.search__index.{tenant}.a.b.c"
    )
    assert (names.events_stream, names.dlq_stream, names.heartbeat_bucket) == (
        "SUPPORTX_EVENTS",
        "SUPPORTX_DLQ",
        "SUPPORTX_HEARTBEATS",
    )


def test_a_namespace_prefixes_every_name() -> None:
    names = BusNames("t1_")
    assert names.events_stream == "T1_SUPPORTX_EVENTS"
    assert names.event_filter(">") == "t1_events.>"
    assert names.dlq_root == "t1_dlq"


# --- consumer declarations -----------------------------------------------------------------------


async def _noop(_event: EventEnvelope, _session: AsyncSession | None) -> None:
    return None


@pytest.mark.parametrize(
    ("name", "event_types", "message"),
    [
        ("Search", ("work_items.ticket.assigned",), "lowercase snake case"),
        ("search_index", ("work_items.ticket.assigned",), "'work_items__<purpose>'"),
        ("work_items__x", (), "subscribes to nothing"),
        ("work_items__x", ("work_items.ticket.renamed",), "not a registered event type"),
        ("work_items__x", ("work_items.*",), "not a registered event type"),
    ],
)
def test_consumer_rules(name: str, event_types: tuple[str, ...], message: str) -> None:
    spec = ConsumerSpec(name=name, event_types=event_types, handler=_noop)
    with pytest.raises(ConsumerRegistrationError, match=message):
        validate_consumer(spec, module="work_items", registry=registry_with(TicketAssigned))


@pytest.mark.parametrize("pattern", [">", "work_items.>", "work_items.ticket.>"])
def test_wildcards_are_allowed(pattern: str) -> None:
    spec = ConsumerSpec(name="work_items__x", event_types=(pattern,), handler=_noop)
    validate_consumer(spec, module="work_items", registry=EventRegistry())


def test_consumers_from_modules() -> None:
    registry = registry_with(TicketAssigned)
    spec = ConsumerSpec(name="work_items__x", event_types=(">",), handler=_noop)
    module = ModuleSpec(name="work_items", consumers=[spec])
    assert consumers_from_modules([module], registry) == [spec]
    with pytest.raises(ConsumerRegistrationError, match="declared twice"):
        consumers_from_modules([ModuleSpec(name="work_items", consumers=[spec, spec])], registry)
    with pytest.raises(ConsumerRegistrationError, match="ConsumerSpec instances"):
        consumers_from_modules([ModuleSpec(name="work_items", consumers=["x"])], registry)


def test_app_consumers_are_valid_and_the_dev_logger_is_dev_only() -> None:
    from conftest import make_settings  # noqa: PLC0415 - shared test helper

    modules = discover_modules()
    specs = consumers_from_modules(modules, EventRegistry.from_modules(modules))
    (logger,) = [s for s in specs if s.name == "system__dev_event_logger"]
    assert logger.enabled(make_settings(profile="dev"))
    assert not logger.enabled(make_settings(profile="test"))
    assert logger.enabled(make_settings(profile="test", dev_event_logger=True))
    production = make_settings(
        profile="production",
        dev_event_logger=True,
        database_url="postgresql://u:p@h:1/d",
        valkey_url="valkey://h:1/0",
        nats_url="nats://h:1",
        oidc_issuer="http://h/realms/x",
        oidc_console_client_secret="c",
        oidc_portal_client_secret="p",
        session_secret="s" * 32,
        centrifugo_api_url="http://127.0.0.1:1",
        centrifugo_api_key="k",
        centrifugo_token_secret="c" * 32,
    )
    assert not logger.enabled(production)  # never in production, whatever the setting says
