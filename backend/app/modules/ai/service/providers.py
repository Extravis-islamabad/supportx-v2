"""One provider interface for every model (REQ-AI-002, architecture.md §12).

Four operations: chat, completion (a chat with one user message), embeddings, and tool calling
(tools on a chat request). Chat streams too. Adding a provider means one more implementation of
`Provider`; no feature changes. Only the gateway uses providers (an import-linter contract keeps
other modules out).

- `FakeProvider` replays recorded answers keyed by feature and a hash of the (masked) prompt,
  and otherwise answers deterministically from the prompt. CI and tests use it, as does
  development on a laptop (product owner: never a large model in Docker on a developer Mac).
- `OpenAICompatibleProvider` is plain HTTP (`httpx`) to a server speaking the OpenAI-compatible
  API: vLLM on a GPU node, the llama.cpp server on CPU (WP-037 session 2), or a cloud endpoint.
"""

import hashlib
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx

from app.core.config import Settings

Role = Literal["system", "user", "assistant"]
EMBEDDING_DIMENSIONS_FAKE = 16


@dataclass(frozen=True)
class Message:
    """One chat message."""

    role: Role
    content: str


@dataclass(frozen=True)
class Tool:
    """A tool the model may ask to call (name, what it does, JSON schema of its arguments)."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """A call the model asked for (run by the caller with the user's permissions, REQ-AI-025)."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatRequest:
    """What a feature asks of a model."""

    feature: str
    messages: tuple[Message, ...]
    max_tokens: int = 800
    temperature: float = 0.2
    tools: tuple[Tool, ...] = ()


@dataclass(frozen=True)
class ChatResult:
    """A model's answer."""

    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)


class ProviderError(RuntimeError):
    """The model could not answer (down, timed out, refused). The gateway logs and reports it."""


class Provider(Protocol):
    """A model behind the gateway."""

    name: str
    model: str
    # Outside the installation: masking is always on (REQ-AI-018).
    external: bool
    supports_tools: bool

    async def chat(self, request: ChatRequest) -> ChatResult:
        """The whole answer."""
        ...

    def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """The answer in pieces, as they come (REQ-AI-002 AC2)."""
        ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text."""
        ...

    async def aclose(self) -> None:
        """Release connections (at shutdown)."""
        ...


def prompt_key(request: ChatRequest) -> str:
    """`<feature>:<sha256 of the messages>`: the key of a recorded answer."""
    body = json.dumps([[m.role, m.content] for m in request.messages], ensure_ascii=False)
    return f"{request.feature}:{hashlib.sha256(body.encode()).hexdigest()}"


class FakeProvider:
    """Recorded answers, else a deterministic one built from the prompt (never a model call)."""

    name = "fake"
    external = False
    supports_tools = False

    def __init__(self, model: str = "fake", recordings: dict[str, str] | None = None) -> None:
        self.model = model
        self.recordings = recordings or {}

    @classmethod
    def from_file(cls, model: str, path: str | None) -> "FakeProvider":
        """With the recordings in `path` (a JSON object), when given."""
        if path is None:
            return cls(model)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(model, {str(k): str(v) for k, v in data.items()})

    def _answer(self, request: ChatRequest) -> str:
        recorded = self.recordings.get(prompt_key(request))
        if recorded is not None:
            return recorded
        last = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
        return f"[{request.feature}] {' '.join(last.split()[:40])}"

    async def chat(self, request: ChatRequest) -> ChatResult:
        """The recorded or deterministic answer; tokens counted as words."""
        text = self._answer(request)
        words = sum(len(m.content.split()) for m in request.messages)
        return ChatResult(text, self.model, input_tokens=words, output_tokens=len(text.split()))

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """Word by word."""
        words = self._answer(request).split(" ")
        for index, word in enumerate(words):
            yield word if index == len(words) - 1 else f"{word} "

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """A stable vector per text from its hash (similar texts are not similar here)."""
        out: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            out.append([b / 255 for b in digest[:EMBEDDING_DIMENSIONS_FAKE]])
        return out

    async def aclose(self) -> None:
        """Nothing to release."""


class OpenAICompatibleProvider:
    """A server speaking the OpenAI-compatible HTTP API (vLLM, llama.cpp server, cloud)."""

    name = "openai_compatible"
    supports_tools = True

    def __init__(  # noqa: PLR0913 - one value per connection setting
        self,
        base_url: str,
        model: str,
        embedding_model: str,
        *,
        api_key: str | None,
        external: bool,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.embedding_model = embedding_model
        self.external = external
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport
        )

    def _body(self, request: ChatRequest, *, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": stream,
        }
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in request.tools
            ]
        return body

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=body)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as error:
            # The error names the status or kind of failure only: never the prompt.
            raise ProviderError(type(error).__name__) from error
        return data

    async def chat(self, request: ChatRequest) -> ChatResult:
        """POST /chat/completions."""
        data = await self._post("/chat/completions", self._body(request, stream=False))
        choice = (data.get("choices") or [{}])[0].get("message") or {}
        calls = tuple(
            ToolCall(
                call["function"]["name"], json.loads(call["function"].get("arguments") or "{}")
            )
            for call in choice.get("tool_calls") or []
        )
        usage = data.get("usage") or {}
        return ChatResult(
            text=choice.get("content") or "",
            model=str(data.get("model") or self.model),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            tool_calls=calls,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """POST /chat/completions with stream: server-sent events, one delta at a time."""
        try:
            async with self._client.stream(
                "POST", "/chat/completions", json=self._body(request, stream=True)
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line.removeprefix("data:").strip()
                    if payload == "[DONE]":
                        return
                    delta = (json.loads(payload).get("choices") or [{}])[0].get("delta") or {}
                    if delta.get("content"):
                        yield str(delta["content"])
        except (httpx.HTTPError, ValueError) as error:
            raise ProviderError(type(error).__name__) from error

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """POST /embeddings."""
        data = await self._post(
            "/embeddings", {"model": self.embedding_model, "input": list(texts)}
        )
        return [list(map(float, item["embedding"])) for item in data.get("data") or []]

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()


def provider_from(settings: Settings) -> Provider:
    """The provider the installation is set up with."""
    if settings.ai_provider == "openai_compatible" and settings.ai_base_url:
        return OpenAICompatibleProvider(
            settings.ai_base_url,
            settings.ai_model,
            settings.ai_embedding_model,
            api_key=None if settings.ai_api_key is None else settings.ai_api_key.get_secret_value(),
            external=settings.ai_provider_external,
            timeout=settings.ai_timeout_seconds,
        )
    return FakeProvider.from_file(settings.ai_model, settings.ai_recordings_path)
