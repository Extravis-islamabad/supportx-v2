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
caller builds the messages from what the subject may see; the gateway never reads records.
"""

import time
import uuid
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass, replace

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.core.errors import EntitlementRequired, PermissionDenied, ServiceUnavailable
from app.core.tenancy import TenantContext
from app.modules.ai.domain.features import feature as feature_spec
from app.modules.ai.domain.masking import CLOSE, OPEN, mask, restore
from app.modules.ai.service import calls
from app.modules.ai.service.providers import ChatRequest, Message, Provider, ProviderError
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
        texts = [m.content for m in messages]
        values: dict[str, str] = {}
        masked = self.provider.external or settings.mask_local
        if masked:
            texts, values = mask(texts, names=names)
        request = ChatRequest(
            feature=feature,
            messages=tuple(replace(m, content=t) for m, t in zip(messages, texts, strict=True)),
            max_tokens=max_tokens,
        )
        return _Prepared(request, values, masked)

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
            masked_input="\n\n".join(f"[{m.role}]\n{m.content}" for m in prepared.request.messages),
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
            raise ServiceUnavailable(code="ai_unavailable") from error
        call_id = await self._log(
            session,
            subject,
            prepared,
            record,
            started,
            model=result.model,
            output=result.text,  # as the model wrote it: masked, never the restored values
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
                output="".join(raw) or None,
                status="failed",
                error_code="ai_provider_unavailable",
            )
            raise ServiceUnavailable(code="ai_unavailable") from error
        if held:
            yield restore(held, prepared.values)
        await self._log(
            session,
            subject,
            prepared,
            record,
            started,
            model=self.provider.model,
            output="".join(raw),
            status="ok",
        )
