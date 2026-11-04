"""The one embedding and retrieval service (WP-037, REQ-AI-057, 058; architecture.md §12).

Every module that wants meaning-based search (similar incidents, knowledge suggestions) goes
through here. They never call a model or touch `ai_embeddings` themselves.

- `index` stores a vector per piece of a record, made by the configured embedding model. A
  piece whose text has not changed (same hash, same model) is not embedded again.
- `search` compares only vectors of the configured model (D-131: vectors of two models never
  meet), then keeps only the records the person may see, asked of the owning module (the same
  check the gateway uses; REQ-AI-025). It returns record IDs and scores, never text.
- A model change leaves the old rows behind. `reembed_sweep` re-embeds them in the background
  through the owning module's text source, so results are never wrong and never mixed.
- Text for an external provider is masked first (REQ-AI-018). The store keeps no text, only a
  hash of it.
"""

import hashlib
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

import structlog
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.ai.domain.masking import mask
from app.modules.ai.infra.models import EMBEDDING_DIMENSION, AiEmbedding
from app.modules.ai.service.providers import Provider, ProviderError
from app.modules.ai.service.records import may_see
from app.modules.ai.service.settings import session_tenant
from app.modules.identity_access import Subject
from app.shared.events import EventEnvelope

log = structlog.get_logger(__name__)

# (session, record IDs) → each record's pieces of text, in order. Registered by the owning module.
TextSource = Callable[
    [AsyncSession, Sequence[uuid.UUID]], Awaitable[Mapping[uuid.UUID, Sequence[str]]]
]

_SOURCES: dict[str, TextSource] = {}

# Pieces per provider call, and stale records re-embedded per tenant per sweep.
BATCH = 32
SWEEP_LIMIT = 200


class EmbeddingWidthError(ValueError):
    """The configured model answers vectors of another width than the store holds (0075)."""


def register_embedding_source(source_type: str, source: TextSource) -> None:
    """The owning module's text for one source type, for re-embedding (at its start-up)."""
    _SOURCES[source_type] = source


def unregister_embedding_source(source_type: str) -> None:
    """At shutdown (tests start the app more than once)."""
    _SOURCES.pop(source_type, None)


@dataclass(frozen=True, slots=True)
class Hit:
    """A record near the query: its ID and how close (1 = same meaning, 0 = unrelated)."""

    source_id: uuid.UUID
    score: float


def _hash(piece: str) -> str:
    return hashlib.sha256(piece.encode()).hexdigest()


def _literal(vector: Sequence[float]) -> str:
    if len(vector) != EMBEDDING_DIMENSION:
        raise EmbeddingWidthError(len(vector))
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


async def remove_record(session: AsyncSession, *, source_type: str, source_id: uuid.UUID) -> None:
    """A record's vectors, of every model, go (no model call)."""
    await session.execute(
        delete(AiEmbedding).where(
            AiEmbedding.source_type == source_type, AiEmbedding.source_id == source_id
        )
    )


class Embeddings:
    """The service over the installation's provider (its embedding model)."""

    def __init__(self, provider: Provider) -> None:
        self.provider = provider

    @property
    def model(self) -> str:
        """The configured embedding model: the only one a search compares."""
        return self.provider.embedding_model

    async def _embed(self, pieces: Sequence[str]) -> list[list[float]]:
        sent = mask(list(pieces), names=())[0] if self.provider.external else list(pieces)
        vectors: list[list[float]] = []
        for start in range(0, len(sent), BATCH):
            vectors.extend(await self.provider.embed(sent[start : start + BATCH]))
        if len(vectors) != len(pieces):
            reason = "embedding_count"
            raise ProviderError(reason)
        return vectors

    async def index(
        self,
        session: AsyncSession,
        *,
        source_type: str,
        source_id: uuid.UUID,
        pieces: Sequence[str],
        actor: uuid.UUID | None = None,
    ) -> int:
        """Store the record's pieces; returns how many were embedded (unchanged ones are not).

        Rows of other models and pieces beyond the new count go: the record has one current set.
        """
        rows = (
            await session.execute(
                select(AiEmbedding.chunk, AiEmbedding.content_hash).where(
                    AiEmbedding.source_type == source_type,
                    AiEmbedding.source_id == source_id,
                    AiEmbedding.model == self.model,
                )
            )
        ).all()
        known: dict[int, str] = dict(rows)  # (chunk, hash) rows
        hashes = [_hash(p) for p in pieces]
        changed = [i for i, digest in enumerate(hashes) if known.get(i) != digest and pieces[i]]
        await session.execute(
            delete(AiEmbedding).where(
                AiEmbedding.source_type == source_type,
                AiEmbedding.source_id == source_id,
                (AiEmbedding.model != self.model) | (AiEmbedding.chunk >= len(pieces)),
            )
        )
        if not changed:
            return 0
        vectors = await self._embed([pieces[i] for i in changed])
        for i, vector in zip(changed, vectors, strict=True):
            statement = insert(AiEmbedding).values(
                id=uuid.uuid4(),
                tenant_id=session_tenant(session),
                source_type=source_type,
                source_id=source_id,
                chunk=i,
                model=self.model,
                dimension=EMBEDDING_DIMENSION,
                content_hash=hashes[i],
                embedding=text(f"'{_literal(vector)}'::vector"),
                created_by=actor,
                updated_by=actor,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["tenant_id", "source_type", "source_id", "chunk", "model"],
                    set_={
                        "content_hash": statement.excluded.content_hash,
                        "embedding": statement.excluded.embedding,
                        "updated_at": func.now(),
                        "updated_by": actor,
                    },
                )
            )
        return len(changed)

    async def remove(
        self, session: AsyncSession, *, source_type: str, source_id: uuid.UUID
    ) -> None:
        """Forget a record (deleted, or no longer to be found), for every model."""
        await remove_record(session, source_type=source_type, source_id=source_id)

    async def search(  # noqa: PLR0913 - the query's parts, explicit
        self,
        session: AsyncSession,
        subject: Subject,
        *,
        source_type: str,
        query: str,
        limit: int = 10,
        exclude: uuid.UUID | None = None,
    ) -> list[Hit]:
        """The records nearest the query that the subject may see, best first.

        The caller is an AI feature, already through the gateway's permission, plan and switch
        checks. Each candidate is checked again with its owning module's rule.
        """
        (vector,) = await self._embed([query])
        distance = AiEmbedding.embedding.op("<=>")(text(f"'{_literal(vector)}'::vector"))
        nearest = (
            select(AiEmbedding.source_id, func.min(distance).label("distance"))
            .where(AiEmbedding.source_type == source_type, AiEmbedding.model == self.model)
            .group_by(AiEmbedding.source_id)
            .order_by(text("distance"))
            .limit(limit * 3)
        )
        if exclude is not None:
            nearest = nearest.where(AiEmbedding.source_id != exclude)
        hits: list[Hit] = []
        for source_id, gap in (await session.execute(nearest)).all():
            if len(hits) == limit:
                break
            if await may_see(session, subject, source_type, source_id):
                hits.append(Hit(source_id, round(1.0 - float(gap), 4)))
        return hits

    async def reembed_stale(self, session: AsyncSession, *, limit: int = SWEEP_LIMIT) -> int:
        """Re-embed records whose vectors came from another model; returns how many records."""
        stale = (
            await session.execute(
                select(AiEmbedding.source_type, AiEmbedding.source_id)
                .where(AiEmbedding.model != self.model)
                .distinct()
                .limit(limit)
            )
        ).all()
        by_type: dict[str, list[uuid.UUID]] = {}
        for source_type, source_id in stale:
            by_type.setdefault(source_type, []).append(source_id)
        done = 0
        for source_type, ids in by_type.items():
            source = _SOURCES.get(source_type)
            if source is None:
                continue  # its module is not running here; the rows wait, never searched
            texts = await source(session, ids)
            for source_id in ids:
                pieces = texts.get(source_id)
                if pieces is None:  # the record is gone
                    await self.remove(session, source_type=source_type, source_id=source_id)
                else:
                    await self.index(
                        session, source_type=source_type, source_id=source_id, pieces=pieces
                    )
                done += 1
        return done


async def reembed_job(database: Database, settings: Settings) -> None:
    """The daily schedule: the sweep with the installation's provider."""
    from app.modules.ai.service.providers import provider_from  # noqa: PLC0415 - one place

    provider = provider_from(settings)
    try:
        await reembed_sweep(database, settings, provider)
    finally:
        await provider.aclose()


async def reembed_sweep(database: Database, settings: Settings, provider: Provider) -> None:
    """In every tenant: vectors of a previous model are re-embedded with the configured one."""
    del settings
    service = Embeddings(provider)
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        try:
            async with database.tenant_session(TenantContext(tenant)) as session:
                done = await service.reembed_stale(session)
        except ProviderError as error:
            log.warning("ai_reembed_failed", tenant_id=str(tenant), error=str(error))
            continue
        if done:
            log.info("ai_reembedded", tenant_id=str(tenant), records=done, model=service.model)


# --- keeping records indexed (WP-038) -------------------------------------------------------------

# The feature whose switch decides whether records are embedded at all (D-134: AI off, no model).
INDEX_FEATURE = "possible_duplicates"
TEXT_FIELDS = {"subject", "description"}


async def on_work_item_changed(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: an incident was created, its text changed, or it was deleted or restored.

    Deleted: its vectors go, whatever the switches (no model needed). Otherwise it is embedded
    through its module's text source, only while AI and possible duplicates are on for the
    tenant and its plan includes AI. Indexing is the system's work, not a person's call, so it
    is not in the AI call log; searches are (`Gateway.similar`).
    """
    assert session is not None  # noqa: S101 - transactional consumer
    payload = envelope.payload
    source_type = str(payload.get("type"))
    record_id = uuid.UUID(str(payload["work_item_id"]))
    if envelope.event_type.endswith(".deleted"):
        await remove_record(session, source_type=source_type, source_id=record_id)
        return
    if envelope.event_type.endswith(".updated") and not TEXT_FIELDS & set(
        payload.get("changed_fields") or ()
    ):
        return
    source = _SOURCES.get(source_type)
    if source is None or not await _indexing_on(session, envelope.tenant_id):
        return
    from app.core.config import get_settings  # noqa: PLC0415 - consumers have no app state
    from app.modules.ai.service.providers import provider_from  # noqa: PLC0415 - one place

    provider = provider_from(get_settings())
    try:
        texts = await source(session, [record_id])
        pieces = texts.get(record_id)
        service = Embeddings(provider)
        if pieces is None:
            await service.remove(session, source_type=source_type, source_id=record_id)
        else:
            await service.index(
                session, source_type=source_type, source_id=record_id, pieces=pieces
            )
    except (ProviderError, EmbeddingWidthError) as error:
        # The model is down or misconfigured: the record waits; searches fall back meanwhile.
        log.warning("ai_index_failed", record_id=str(record_id), error=type(error).__name__)
    finally:
        await provider.aclose()


async def _indexing_on(session: AsyncSession, tenant_id: uuid.UUID) -> bool:
    from app.modules.ai.service.settings import feature_on, settings_row  # noqa: PLC0415 - cycle
    from app.modules.licensing import has_feature  # noqa: PLC0415 - cycle

    if not await has_feature(tenant_id, "ai_assist"):
        return False
    return feature_on(await settings_row(session), INDEX_FEATURE)
