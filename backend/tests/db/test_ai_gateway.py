"""The AI gateway against a real database (WP-037; REQ-AI-001, 018, 025, 027, 031).

- In order: permission, plan, switches, masking, provider, log; refusals and failures are logged
  in their own transaction, so they survive the caller's rollback.
- An external provider never sees personal data; the person sees it restored.
- A streamed answer never shows half a placeholder.
- Settings change with If-Match, history and an outbox event.
- The call log is isolated per tenant (RLS), and its text is cleared after the retention period.
"""

import json
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING

import asyncpg
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    ServiceUnavailable,
    ValidationFailed,
)
from app.core.modules import ModuleRegistry, discover_modules
from app.core.tenancy import TenantContext
from app.main import create_app
from app.modules.ai import GATEWAY_STATE, Gateway, Message, Record
from app.modules.ai.infra.models import AiCall
from app.modules.ai.service.calls import purge_text, set_outcome
from app.modules.ai.service.providers import ChatRequest, ChatResult, FakeProvider, ProviderError
from app.modules.ai.service.settings import settings_row, update_settings
from app.modules.identity_access.domain.policy import Grant, Subject
from app.shared.clock import system_clock
from app.shared.history import Source
from conftest import create_tenant, make_settings
from tooling.db_testing import ThrowawayDatabase

if TYPE_CHECKING:
    from app.core.database import Database

pytestmark = pytest.mark.db

ALL = (Grant(scope="all"),)
SOURCE: Source = "ui"


def subject(tenant: uuid.UUID, *permissions: str) -> Subject:
    return Subject(
        tenant_id=tenant,
        user_id=uuid.uuid4(),
        role_keys=frozenset({"technician"}),
        is_tenant_admin=False,
        grants=MappingProxyType(dict.fromkeys(permissions, ALL)),
    )


class ExternalFake(FakeProvider):
    """A provider outside the installation that records what it was sent."""

    name = "cloud_fake"
    external = True

    def __init__(self) -> None:
        super().__init__("cloud-model")
        self.seen: list[ChatRequest] = []

    async def chat(self, request: ChatRequest) -> ChatResult:
        self.seen.append(request)
        # Answers with the masked placeholder, as a model would when it refers to the person.
        mentioned = next(
            p for p in ("⟦EMAIL_1⟧", "⟦PERSON_1⟧") if p in request.messages[-1].content
        )
        return ChatResult(f"Write to {mentioned} today.", self.model)


class Broken(FakeProvider):
    async def chat(self, request: ChatRequest) -> ChatResult:
        del request
        kind = "ConnectError"
        raise ProviderError(kind)


class Chunked(FakeProvider):
    """Streams a placeholder split across two pieces."""

    external = True

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        del request
        for piece in ("Mail ", "⟦EMA", "IL_1⟧", " now."):
            yield piece


class World:
    def __init__(
        self, app: FastAPI, db: ThrowawayDatabase, tenant: uuid.UUID, other: uuid.UUID
    ) -> None:
        self.app, self.db, self.tenant, self.other = app, db, tenant, other

    def session(self, tenant: uuid.UUID | None = None) -> AbstractAsyncContextManager[AsyncSession]:
        database: Database = self.app.state.db
        return database.tenant_session(TenantContext(tenant or self.tenant))

    def gateway(self, provider: FakeProvider) -> Gateway:
        return Gateway(provider, self.app.state.db)

    async def calls(self, tenant: uuid.UUID | None = None) -> Sequence[AiCall]:
        async with self.session(tenant) as session:
            found = await session.scalars(select(AiCall).order_by(AiCall.created_at))
            return list(found.all())


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    app = create_app(
        make_settings(database_url=migrated_db.app_url),
        ModuleRegistry.from_specs(discover_modules()),
    )
    tenant = await create_tenant(migrated_db.migrator_url, "AI A")
    other = await create_tenant(migrated_db.migrator_url, "AI B")
    async with app.router.lifespan_context(app):
        yield World(app, migrated_db, tenant, other)


SUMMARY = [Message("system", "Summarise."), Message("user", "Printer jams on floor 3.")]


async def test_the_gateway_is_started_with_the_fake_and_answers(world: World) -> None:
    gateway: Gateway = getattr(world.app.state, GATEWAY_STATE)
    assert gateway.provider.name == "fake"
    tech = subject(world.tenant, "incidents.view")
    async with world.session() as session:
        answer = await gateway.chat(
            session,
            tech,
            feature="conversation_summary",
            messages=SUMMARY,
            record=Record("incident", uuid.uuid4()),
        )
    assert answer.text == "[conversation_summary] Printer jams on floor 3."
    [call] = await world.calls()
    assert (call.id, call.status, call.feature, call.user_id) == (
        answer.call_id,
        "ok",
        "conversation_summary",
        tech.user_id,
    )
    assert call.record_type == "incident"
    assert "Printer jams" in (call.masked_input or "")
    assert call.masked is False  # a local model, local masking off


async def test_refusals_come_in_order_and_are_logged_even_when_the_caller_rolls_back(
    world: World,
) -> None:
    gateway = world.gateway(FakeProvider())
    nobody = subject(world.tenant)
    with pytest.raises(PermissionDenied):
        async with world.session() as session:
            await gateway.chat(session, nobody, feature="conversation_summary", messages=SUMMARY)
    admin = subject(world.tenant, "ai.manage", "incidents.view")
    async with world.session() as session:
        row = await settings_row(session)
        await update_settings(
            session,
            admin,
            {"disabled_features": ["conversation_summary"]},
            expected_version=row.version,
            source=SOURCE,
        )
    with pytest.raises(PermissionDenied) as off:
        async with world.session() as session:
            await gateway.chat(session, admin, feature="conversation_summary", messages=SUMMARY)
    assert off.value.instance_code == "ai_feature_off"
    calls = await world.calls()
    assert [(c.status, c.error_code) for c in calls] == [
        ("refused", "permission_denied"),
        ("refused", "ai_feature_off"),
    ]
    assert all(c.masked_input is None for c in calls)  # a refused call sends nothing anywhere


async def test_an_external_model_sees_only_placeholders_and_the_person_sees_the_values(
    world: World,
) -> None:
    provider = ExternalFake()
    gateway = world.gateway(provider)
    tech = subject(world.tenant, "incidents.reply")
    async with world.session() as session:
        answer = await gateway.chat(
            session,
            tech,
            feature="reply_draft",
            messages=[Message("user", "Ali Raza (ali@example.com) cannot print.")],
            names=["Ali Raza"],
        )
    sent = provider.seen[0].messages[0].content
    assert "Ali Raza" not in sent
    assert "ali@example.com" not in sent
    assert answer.text == "Write to ali@example.com today."
    [call] = await world.calls()
    assert call.masked is True
    assert call.masked_values == 2
    assert "ali@example.com" not in (call.masked_input or "") + (call.output or "")


async def test_a_failing_model_is_logged_and_reported_without_detail(world: World) -> None:
    gateway = world.gateway(Broken())
    tech = subject(world.tenant, "incidents.view")
    with pytest.raises(ServiceUnavailable) as raised:
        async with world.session() as session:
            await gateway.chat(session, tech, feature="conversation_summary", messages=SUMMARY)
    assert raised.value.instance_code == "ai_unavailable"
    [call] = await world.calls()
    assert (call.status, call.error_code) == ("failed", "ai_provider_unavailable")


async def test_a_stream_never_shows_half_a_placeholder(world: World) -> None:
    gateway = world.gateway(Chunked())
    tech = subject(world.tenant, "incidents.reply")
    async with world.session() as session:
        pieces = [
            piece
            async for piece in gateway.stream(
                session,
                tech,
                feature="reply_draft",
                messages=[Message("user", "Mail sara@example.com now.")],
            )
        ]
    assert "".join(pieces) == "Mail sara@example.com now."
    assert all("⟦" not in piece and "⟧" not in piece for piece in pieces)
    [call] = await world.calls()
    assert call.status == "ok"
    assert call.output == "Mail ⟦EMAIL_1⟧ now."


async def test_settings_need_the_right_the_version_and_valid_values(world: World) -> None:
    tech = subject(world.tenant, "incidents.view")
    admin = subject(world.tenant, "ai.manage")
    async with world.session() as session:
        row = await settings_row(session)
        assert (row.enabled, row.disabled_features, row.log_retention_days) == (True, [], 30)
        with pytest.raises(PermissionDenied):
            await update_settings(
                session, tech, {"enabled": False}, expected_version=row.version, source=SOURCE
            )
        with pytest.raises(Conflict):
            await update_settings(
                session, admin, {"enabled": False}, expected_version=99, source=SOURCE
            )
        with pytest.raises(ValidationFailed):
            await update_settings(
                session,
                admin,
                {"disabled_features": ["no_such_feature"], "log_retention_days": 999},
                expected_version=row.version,
                source=SOURCE,
            )
        saved = await update_settings(
            session,
            admin,
            {"enabled": False, "log_retention_days": 60},
            expected_version=row.version,
            source=SOURCE,
        )
        assert (saved.enabled, saved.log_retention_days, saved.version) == (False, 60, 2)
    # The app role cannot read the outbox; the admin connection checks the event.
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        events = await conn.fetch(
            "SELECT envelope->'payload'->>'changed_fields' AS fields FROM outbox_events"
            " WHERE event_type = 'ai.settings.changed' AND tenant_id = $1",
            world.tenant,
        )
    finally:
        await conn.close()
    assert [json.loads(e["fields"]) for e in events] == [["enabled", "log_retention_days"]]


async def test_the_call_log_is_isolated_by_tenant(world: World) -> None:
    gateway = world.gateway(FakeProvider())
    async with world.session() as session:
        await gateway.chat(
            session,
            subject(world.tenant, "incidents.view"),
            feature="conversation_summary",
            messages=SUMMARY,
        )
    assert len(await world.calls()) == 1
    assert await world.calls(world.other) == []
    async with world.session(world.other) as session:
        changed = await session.execute(update(AiCall).values(output="tampered"))
        assert getattr(changed, "rowcount", 0) == 0
        assert await session.scalar(text("SELECT count(*) FROM ai_settings")) == 0


async def test_call_text_is_cleared_after_the_retention_period_and_the_row_stays(
    world: World,
) -> None:
    gateway = world.gateway(FakeProvider())
    tech = subject(world.tenant, "incidents.view")
    async with world.session() as session:
        old = await gateway.chat(session, tech, feature="conversation_summary", messages=SUMMARY)
        new = await gateway.chat(session, tech, feature="conversation_summary", messages=SUMMARY)
    async with world.session() as session:
        await session.execute(
            update(AiCall)
            .where(AiCall.id == old.call_id)
            .values(created_at=system_clock.now() - timedelta(days=31))
        )
    async with world.session() as session:
        assert await purge_text(session) == 1
    rows = {c.id: c for c in await world.calls()}
    assert rows[old.call_id].masked_input is None
    assert rows[old.call_id].output is None
    assert rows[old.call_id].text_purged_at is not None
    assert rows[old.call_id].status == "ok"  # counts and outcome stay
    assert rows[new.call_id].output is not None
    # A longer retention keeps it.
    admin = subject(world.tenant, "ai.manage")
    async with world.session() as session:
        row = await settings_row(session)
        await update_settings(
            session, admin, {"log_retention_days": 60}, expected_version=row.version, source=SOURCE
        )
        await session.execute(
            update(AiCall)
            .where(AiCall.id == new.call_id)
            .values(created_at=system_clock.now() - timedelta(days=45))
        )
    async with world.session() as session:
        assert await purge_text(session) == 0


async def test_only_the_caller_records_what_they_did_with_the_answer(world: World) -> None:
    gateway = world.gateway(FakeProvider())
    tech = subject(world.tenant, "incidents.view")
    async with world.session() as session:
        answer = await gateway.chat(session, tech, feature="conversation_summary", messages=SUMMARY)
    async with world.session() as session:
        with pytest.raises(NotFound):
            await set_outcome(session, subject(world.tenant), answer.call_id, "accepted")
    async with world.session() as session:
        await set_outcome(session, tech, answer.call_id, "edited")
    [call] = await world.calls()
    assert call.outcome == "edited"
