"""The one AI gateway (REQ-AI-001, architecture.md §12).

Every AI call in SupportX goes through `Gateway.chat` or `Gateway.stream`; no module calls a
model directly (import-linter keeps the providers private to this module). In this fixed order:

1. the caller's permission for the feature (REQ-AI-025), through the one policy layer;
2. the plan includes AI (`has_feature`, the entitlement interface only, REQ-AI-108);
3. the master switch and the feature's switch (REQ-AI-027);
4. masking: always for an external provider, for the local model when the tenant asks
   (REQ-AI-018);
5. the provider;
6. the call log, for every outcome: answered, refused, failed (REQ-AI-031). The log entry is
   written in its own transaction, so a refusal or a failure that rolls the caller's work back
   is still recorded.

Quotas are not applied yet: they come with the cost and quota settings (REQ-AI-030, V1). The
caller builds the messages from what the subject may see; the gateway never reads records. A call
about a record is checked again here through the record's owning module (`register_record_access`,
architecture.md §11.2), failing closed. The gateway only returns text: it never writes a record,
so an answer is always a suggestion a person reviews and confirms (REQ-INC-136).

The log always holds a masked copy, even when the model itself saw the text unmasked (a local
model with local masking off): personal data never sits in the call log.
"""

import time
import uuid
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass, replace

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.core.errors import EntitlementRequired, NotFound, PermissionDenied, ServiceUnavailable
from app.core.tenancy import TenantContext
from app.modules.ai.domain.features import feature as feature_spec
from app.modules.ai.domain.masking import CLOSE, OPEN, mask, restore
from app.modules.ai.service import calls
from app.modules.ai.service.embeddings import Embeddings, EmbeddingWidthError, Hit
from app.modules.ai.service.providers import (
    ChatRequest,
    Message,
    Provider,
    ProviderError,
    ProviderNotConfigured,
)
from app.modules.ai.service.records import may_see
from app.modules.ai.service.settings import feature_on, settings_row
from app.modules.identity_access import Subject
from app.modules.licensing import has_feature

AI_FEATURE = "ai_assist"  # the licence feature every assist feature needs (Essentials and up)


@dataclass(frozen=True)
class AiAnswer:
    """A model's answer as the person sees it (restored), with its log entry."""

    call_id: uuid.UUID
    text: str
    model: str


@dataclass(frozen=True)
class Record:
    """The record an AI call is about (for the log)."""

    type: str
    id: uuid.UUID


@dataclass
class _Prepared:
    request: ChatRequest
    values: dict[str, str]
    masked: bool
    # What the log keeps: always masked, whatever the model saw.
    log_input: str
    names: tuple[str, ...]

    def log_output(self, text: str) -> str:
        """The answer as the log keeps it: masked (an unmasked model may repeat personal data)."""
        if self.masked:
            return text
        [masked], _ = mask([text], names=self.names)
        return masked


class Gateway:
    """The gateway over one provider (the installation's)."""

    def __init__(self, provider: Provider, database: Database | None = None) -> None:
        self.provider = provider
        # The log's own transactions; without a database (unit tests) the caller's session.
        self.database = database

    async def _write(self, session: AsyncSession, subject: Subject, **fields: object) -> uuid.UUID:
        if self.database is None:
            return (await calls.record_call(session, **fields)).id
        context = TenantContext(subject.tenant_id, subject.user_id)
        async with self.database.tenant_session(context) as own:
            return (await calls.record_call(own, **fields)).id

    async def _refuse(  # noqa: PLR0913 - the log entry's facts
        self,
        session: AsyncSession,
        subject: Subject,
        *,
        code: str,
        feature: str,
        record: Record | None,
        error: Exception,
    ) -> Exception:
        await self._write(
            session,
            subject,
            feature=feature,
            user_id=subject.user_id,
            record_type=None if record is None else record.type,
            record_id=None if record is None else record.id,
            provider=self.provider.name,
            model=self.provider.model,
            status="refused",
            error_code=code,
        )
        return error

    async def _prepare(  # noqa: PLR0913 - the request's parts, explicit
        self,
        session: AsyncSession,
        subject: Subject,
        *,
        feature: str,
        messages: Sequence[Message],
        record: Record | None,
        names: Iterable[str],
        max_tokens: int,
    ) -> _Prepared:
        spec = feature_spec(feature)
        if spec is None:
            raise ValueError(feature)  # a programming error: features are declared in domain
        if not subject.holds(spec.permission):
            raise await self._refuse(
                session,
                subject,
                code="permission_denied",
                feature=feature,
                record=record,
                error=PermissionDenied(params={"permission": spec.permission}),
            )
        if not await has_feature(subject.tenant_id, AI_FEATURE):
            raise await self._refuse(
                session,
                subject,
                code="entitlement_required",
                feature=feature,
                record=record,
                error=EntitlementRequired(params={"feature": AI_FEATURE}),
            )
        if record is not None and not await may_see(session, subject, record.type, record.id):
            raise await self._refuse(
                session,
                subject,
                code="ai_record_not_visible",
                feature=feature,
                record=record,
                error=NotFound(code="ai_record_not_visible"),
            )
        settings = await settings_row(session)
        if not feature_on(settings, feature):
            raise await self._refuse(
                session,
                subject,
                code="ai_feature_off",
                feature=feature,
                record=record,
                error=PermissionDenied(code="ai_feature_off", params={"feature": feature}),
            )
        names = tuple(names)
        texts = [m.content for m in messages]
        masked_texts, values = mask(texts, names=names)
        masked = self.provider.external or settings.mask_local
        sent = masked_texts if masked else texts
        request = ChatRequest(
            feature=feature,
            messages=tuple(replace(m, content=t) for m, t in zip(messages, sent, strict=True)),
            max_tokens=max_tokens,
        )
        log_input = "\n\n".join(
            f"[{m.role}]\n{t}" for m, t in zip(messages, masked_texts, strict=True)
        )
        return _Prepared(request, values if masked else {}, masked, log_input, names)

    async def _log(
        self,
        session: AsyncSession,
        subject: Subject,
        prepared: _Prepared,
        record: Record | None,
        started: float,
        **result: object,
    ) -> uuid.UUID:
        return await self._write(
            session,
            subject,
            feature=prepared.request.feature,
            user_id=subject.user_id,
            record_type=None if record is None else record.type,
            record_id=None if record is None else record.id,
            provider=self.provider.name,
            masked=prepared.masked,
            masked_values=len(prepared.values),
            masked_input=prepared.log_input,
            latency_ms=int((time.monotonic() - started) * 1000),
            **result,
        )

    async def chat(  # noqa: PLR0913 - the request's parts, explicit
        self,
        session: AsyncSession,
        subject: Subject,
        *,
        feature: str,
        messages: Sequence[Message],
        record: Record | None = None,
        names: Iterable[str] = (),
        max_tokens: int = 800,
    ) -> AiAnswer:
        """The whole answer, restored, after every check; logged whatever happens."""
        prepared = await self._prepare(
            session,
            subject,
            feature=feature,
            messages=messages,
            record=record,
            names=names,
            max_tokens=max_tokens,
        )
        started = time.monotonic()
        try:
            result = await self.provider.chat(prepared.request)
        except ProviderError as error:
            await self._log(
                session,
                subject,
                prepared,
                record,
                started,
                model=self.provider.model,
                status="failed",
                error_code="ai_provider_unavailable",
            )
            # No model on this installation: say so, never a prompt echo (QA6-AI-01).
            code = (
                "ai_not_configured"
                if isinstance(error, ProviderNotConfigured)
                else "ai_unavailable"
            )
            raise ServiceUnavailable(code=code) from error
        call_id = await self._log(
            session,
            subject,
            prepared,
            record,
            started,
            model=result.model,
            output=prepared.log_output(result.text),  # never the restored values
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            tools=[{"name": c.name} for c in result.tool_calls],
            status="ok",
        )
        return AiAnswer(call_id, restore(result.text, prepared.values), result.model)

    async def stream(  # noqa: PLR0913 - the request's parts, explicit
        self,
        session: AsyncSession,
        subject: Subject,
        *,
        feature: str,
        messages: Sequence[Message],
        record: Record | None = None,
        names: Iterable[str] = (),
        max_tokens: int = 800,
    ) -> AsyncIterator[str]:
        """The answer in pieces, restored as they come (REQ-AI-002 AC2); logged at the end.

        A placeholder split across two pieces is held back until it is whole, so a person never
        sees half a placeholder and the restored value is always complete.
        """
        prepared = await self._prepare(
            session,
            subject,
            feature=feature,
            messages=messages,
            record=record,
            names=names,
            max_tokens=max_tokens,
        )
        started = time.monotonic()
        raw: list[str] = []
        held = ""
        try:
            async for piece in self.provider.stream(prepared.request):
                raw.append(piece)
                held += piece
                cut = held.rfind(OPEN)
                if cut != -1 and CLOSE not in held[cut:]:
                    ready, held = held[:cut], held[cut:]
                else:
                    ready, held = held, ""
                if ready:
                    yield restore(ready, prepared.values)
        except ProviderError as error:
            await self._log(
                session,
                subject,
                prepared,
                record,
                started,
                model=self.provider.model,
                output=prepared.log_output("".join(raw)) or None,
                status="failed",
                error_code="ai_provider_unavailable",
            )
            # No model on this installation: say so, never a prompt echo (QA6-AI-01).
            code = (
                "ai_not_configured"
                if isinstance(error, ProviderNotConfigured)
                else "ai_unavailable"
            )
            raise ServiceUnavailable(code=code) from error
        if held:
            yield restore(held, prepared.values)
        await self._log(
            session,
            subject,
            prepared,
            record,
            started,
            model=self.provider.model,
            output=prepared.log_output("".join(raw)),
            status="ok",
        )

    async def available(self, session: AsyncSession, subject: Subject, feature: str) -> bool:
        """Whether a feature would run for this person now: permission, plan and switches.

        For features with a non-AI fallback (possible duplicates, D-134): false means use it,
        with no model call at all.
        """
        spec = feature_spec(feature)
        if spec is None or not subject.holds(spec.permission):
            return False
        if not await has_feature(subject.tenant_id, AI_FEATURE):
            return False
        return feature_on(await settings_row(session), feature)

    async def similar(  # noqa: PLR0913 - the search's parts, explicit
        self,
        session: AsyncSession,
        subject: Subject,
        *,
        feature: str,
        source_type: str,
        query: str,
        limit: int = 5,
        exclude: uuid.UUID | None = None,
    ) -> list[Hit] | None:
        """Records near `query` by meaning that the person may see, or None when AI may not run.

        None (AI off, no plan, a failing model) tells the caller to use its non-AI fallback. A
        search that runs is logged like every AI call: the masked query and how many it found.
        """
        if not await self.available(session, subject, feature):
            return None
        masked_texts, values = mask([query], names=())
        started = time.monotonic()
        fields: dict[str, object] = {
            "feature": feature,
            "user_id": subject.user_id,
            "provider": self.provider.name,
            "model": self.provider.embedding_model,
            "masked": bool(values),
            "masked_values": len(values),
            "masked_input": masked_texts[0],
        }
        try:
            settings = await settings_row(session)
            hits = await Embeddings(self.provider, mask_local=settings.mask_local).search(
                session, subject, source_type=source_type, query=query, limit=limit, exclude=exclude
            )
        except (ProviderError, EmbeddingWidthError):
            await self._write(
                session,
                subject,
                **fields,
                latency_ms=int((time.monotonic() - started) * 1000),
                status="failed",
                error_code="ai_provider_unavailable",
            )
            return None
        await self._write(
            session,
            subject,
            **fields,
            output=f"{len(hits)} found",
            sources=[{"type": source_type, "id": str(h.source_id)} for h in hits],
            latency_ms=int((time.monotonic() - started) * 1000),
            status="ok",
        )
        return hits
