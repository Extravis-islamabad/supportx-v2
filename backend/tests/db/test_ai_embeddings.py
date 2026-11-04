"""The embedding and retrieval service against a real database (WP-037; REQ-AI-057, 058, 025).

- Vectors are isolated per tenant (RLS): tenant B can neither read nor change tenant A's rows.
- Unchanged text is not embedded again; a shorter record loses its extra pieces.
- A search compares only the configured model's vectors (D-131) and keeps only the records the
  person may see, asked of the owning module.
- After a model change, the sweep re-embeds old rows through the owning module's text source;
  rows of a module not running here wait, and are never searched.
- A model of another width is refused, never stored.
"""

import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.modules import ModuleRegistry, discover_modules
from app.core.tenancy import TenantContext
from app.main import create_app
from app.modules.ai import register_record_access, unregister_record_access
from app.modules.ai.infra.models import AiEmbedding
from app.modules.ai.service.embeddings import (
    Embeddings,
    EmbeddingWidthError,
    reembed_sweep,
    register_embedding_source,
    unregister_embedding_source,
)
from app.modules.ai.service.providers import FakeProvider
from app.modules.identity_access.domain.policy import Grant, Subject
from conftest import create_tenant, make_settings
from tooling.db_testing import ThrowawayDatabase

if TYPE_CHECKING:
    from fastapi import FastAPI

    from app.core.database import Database

pytestmark = pytest.mark.db

ARTICLES = {
    "vpn": "The VPN drops every hour on the office network",
    "printer": "The printer on floor 3 is out of toner",
    "mail": "Outlook asks for the password again and again",
}


class Counting(FakeProvider):
    """The fake, counting what it embeds."""

    def __init__(self, embedding_model: str = "fake-embeddings") -> None:
        super().__init__(embedding_model=embedding_model)
        self.embedded: list[str] = []

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.embedded.extend(texts)
        return await super().embed(texts)


class Narrow(FakeProvider):
    """A model whose vectors are not 1024 wide."""

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.5] * 768 for _ in texts]


def subject(tenant: uuid.UUID) -> Subject:
    return Subject(
        tenant_id=tenant,
        user_id=uuid.uuid4(),
        role_keys=frozenset({"technician"}),
        is_tenant_admin=False,
        grants=MappingProxyType({"incidents.view": (Grant(scope="all"),)}),
    )


class World:
    def __init__(self, app: "FastAPI", tenant: uuid.UUID, other: uuid.UUID) -> None:
        self.app, self.tenant, self.other = app, tenant, other
        self.visible: set[uuid.UUID] = set()
        self.texts: dict[uuid.UUID, list[str]] = {}

    def session(self, tenant: uuid.UUID | None = None) -> AbstractAsyncContextManager[AsyncSession]:
        database: Database = self.app.state.db
        return database.tenant_session(TenantContext(tenant or self.tenant))

    async def rows(self, tenant: uuid.UUID | None = None) -> list[AiEmbedding]:
        async with self.session(tenant) as session:
            return list((await session.scalars(select(AiEmbedding))).all())


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    app = create_app(
        make_settings(database_url=migrated_db.app_url),
        ModuleRegistry.from_specs(discover_modules()),
    )
    tenant = await create_tenant(migrated_db.migrator_url, "Embeddings A")
    other = await create_tenant(migrated_db.migrator_url, "Embeddings B")
    world = World(app, tenant, other)

    async def access(session: AsyncSession, who: Subject, record_id: uuid.UUID) -> bool:
        del session, who
        return record_id in world.visible

    async def source(
        session: AsyncSession, ids: Sequence[uuid.UUID]
    ) -> Mapping[uuid.UUID, Sequence[str]]:
        del session
        return {i: world.texts[i] for i in ids if i in world.texts}

    async with app.router.lifespan_context(app):
        register_record_access("kb_article", access)
        register_embedding_source("kb_article", source)
        try:
            yield world
        finally:
            unregister_record_access("kb_article")
            unregister_embedding_source("kb_article")


async def _index_articles(world: World, service: Embeddings) -> dict[str, uuid.UUID]:
    ids = {key: uuid.uuid4() for key in ARTICLES}
    async with world.session() as session:
        for key, body in ARTICLES.items():
            world.texts[ids[key]] = [body]
            await service.index(
                session, source_type="kb_article", source_id=ids[key], pieces=[body]
            )
    return ids


async def test_vectors_are_isolated_by_tenant(world: World) -> None:
    await _index_articles(world, Embeddings(FakeProvider()))
    assert len(await world.rows()) == 3
    assert await world.rows(world.other) == []
    async with world.session(world.other) as session:
        changed = await session.execute(update(AiEmbedding).values(content_hash="x" * 64))
        assert getattr(changed, "rowcount", 0) == 0
        assert await session.scalar(text("SELECT count(*) FROM ai_embeddings")) == 0


async def test_unchanged_text_is_not_embedded_again_and_extra_pieces_go(world: World) -> None:
    provider = Counting()
    service = Embeddings(provider)
    record = uuid.uuid4()
    async with world.session() as session:
        first = await service.index(
            session, source_type="kb_article", source_id=record, pieces=["One part", "Two part"]
        )
        again = await service.index(
            session, source_type="kb_article", source_id=record, pieces=["One part", "Two part"]
        )
        edited = await service.index(
            session, source_type="kb_article", source_id=record, pieces=["One part changed"]
        )
    assert (first, again, edited) == (2, 0, 1)
    assert provider.embedded == ["One part", "Two part", "One part changed"]
    rows = await world.rows()
    assert [(r.chunk, r.model, r.dimension) for r in rows] == [(0, "fake-embeddings", 1024)]


async def test_a_search_finds_the_nearest_records_the_person_may_see(world: World) -> None:
    service = Embeddings(FakeProvider())
    ids = await _index_articles(world, service)
    world.visible = {ids["vpn"], ids["printer"]}
    who = subject(world.tenant)
    async with world.session() as session:
        hits = await service.search(
            session, who, source_type="kb_article", query="vpn drops", limit=2
        )
        hidden = await service.search(
            session, who, source_type="kb_article", query="Outlook password", limit=3
        )
        excluded = await service.search(
            session,
            who,
            source_type="kb_article",
            query="vpn drops",
            limit=2,
            exclude=ids["vpn"],
        )
    assert hits[0].source_id == ids["vpn"]
    assert hits[0].score > hits[1].score
    # The mail article is the nearest to its own words, but the person may not see it.
    assert ids["mail"] not in {h.source_id for h in hidden}
    assert ids["vpn"] not in {h.source_id for h in excluded}
    # Another tenant's search finds nothing of this one.
    async with world.session(world.other) as session:
        assert (
            await service.search(
                session, subject(world.other), source_type="kb_article", query="vpn drops"
            )
            == []
        )


async def test_vectors_of_two_models_never_meet_and_the_sweep_reembeds(world: World) -> None:
    old = Embeddings(FakeProvider(embedding_model="old-model"))
    ids = await _index_articles(world, old)
    world.visible = set(ids.values())
    orphan = uuid.uuid4()  # a record whose module does not run here
    async with world.session() as session:
        await old.index(session, source_type="ticket", source_id=orphan, pieces=["vpn drops"])
    provider = Counting("new-model")
    new = Embeddings(provider)
    who = subject(world.tenant)
    async with world.session() as session:
        assert await new.search(session, who, source_type="kb_article", query="vpn drops") == []
    provider.embedded.clear()  # the query above; count only what the sweep embeds

    await reembed_sweep(world.app.state.db, make_settings(), provider)

    rows = await world.rows()
    models = {(r.source_type, r.model) for r in rows}
    assert models == {("kb_article", "new-model"), ("ticket", "old-model")}
    # The sweep runs in every tenant: other tests' tenants in this database may be swept too.
    assert set(ARTICLES.values()) <= set(provider.embedded)
    async with world.session() as session:
        hits = await new.search(session, who, source_type="kb_article", query="vpn drops")
        stale_hits = await new.search(session, who, source_type="ticket", query="vpn drops")
    assert hits[0].source_id == ids["vpn"]
    assert stale_hits == []


async def test_a_record_gone_from_its_module_is_forgotten_by_the_sweep(world: World) -> None:
    ids = await _index_articles(world, Embeddings(FakeProvider(embedding_model="old-model")))
    del world.texts[ids["mail"]]
    await reembed_sweep(world.app.state.db, make_settings(), FakeProvider())
    async with world.session() as session:
        left = await session.scalar(
            select(func.count()).where(AiEmbedding.source_id == ids["mail"])
        )
    assert left == 0


async def test_a_model_of_another_width_is_refused_never_stored(world: World) -> None:
    service = Embeddings(Narrow())
    async with world.session() as session:
        with pytest.raises(EmbeddingWidthError):
            await service.index(
                session, source_type="kb_article", source_id=uuid.uuid4(), pieces=["vpn"]
            )
    assert await world.rows() == []


async def test_text_is_masked_before_embedding_when_the_admin_asks(world: World) -> None:
    provider = Counting()
    async with world.session() as session:
        await Embeddings(provider, mask_local=True).index(
            session,
            source_type="kb_article",
            source_id=uuid.uuid4(),
            pieces=["Mail ali@example.com about the VPN"],
        )
        await Embeddings(provider).index(
            session, source_type="kb_article", source_id=uuid.uuid4(), pieces=["Plain VPN text"]
        )
    masked, plain = provider.embedded
    assert "ali@example.com" not in masked
    assert "⟦EMAIL_1⟧" in masked
    assert plain == "Plain VPN text"  # local, masking not asked for: as for calls
