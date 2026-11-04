"""The provider interface: the fake and the OpenAI-compatible HTTP provider (REQ-AI-002)."""

import json

import httpx
import pytest

from app.modules.ai.service.providers import (
    ChatRequest,
    FakeProvider,
    Message,
    OpenAICompatibleProvider,
    ProviderError,
    Tool,
    prompt_key,
    provider_from,
)
from conftest import make_settings

REQUEST = ChatRequest(
    feature="conversation_summary",
    messages=(Message("system", "Summarise."), Message("user", "The printer on floor 3 jams.")),
)


async def test_the_fake_replays_a_recording_else_answers_from_the_prompt() -> None:
    recorded = FakeProvider(recordings={prompt_key(REQUEST): "Printer jams; not yet fixed."})
    assert (await recorded.chat(REQUEST)).text == "Printer jams; not yet fixed."
    plain = FakeProvider()
    answer = await plain.chat(REQUEST)
    assert answer.text == "[conversation_summary] The printer on floor 3 jams."
    assert answer.input_tokens == 7
    pieces = [piece async for piece in plain.stream(REQUEST)]
    assert pieces[0] == "[conversation_summary] "
    assert "".join(pieces) == answer.text
    first, again = await plain.embed(["vpn"]), await plain.embed(["vpn"])
    assert first == again
    assert len(first[0]) == 16


def _provider(handler: httpx.MockTransport) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        "http://model.local/v1",
        "qwen",
        "bge-m3",
        api_key="k",
        external=False,
        timeout=5,
        transport=handler,
    )


async def test_chat_tools_and_embeddings_over_http() -> None:
    seen: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"path": request.url.path, "auth": request.headers["authorization"], **body})
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        return httpx.Response(
            200,
            json={
                "model": "qwen-14b",
                "choices": [
                    {
                        "message": {
                            "content": "Done.",
                            "tool_calls": [
                                {"function": {"name": "find", "arguments": '{"q": "vpn"}'}}
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 2},
            },
        )

    provider = _provider(httpx.MockTransport(handle))
    tool = Tool("find", "Find articles", {"type": "object"})
    answer = await provider.chat(
        ChatRequest(feature="reply_draft", messages=REQUEST.messages, tools=(tool,))
    )
    assert (answer.text, answer.model, answer.input_tokens) == ("Done.", "qwen-14b", 12)
    assert answer.tool_calls[0].name == "find"
    assert answer.tool_calls[0].arguments == {"q": "vpn"}
    assert seen[0]["path"] == "/v1/chat/completions"
    assert seen[0]["auth"] == "Bearer k"
    assert seen[0]["tools"][0]["function"]["name"] == "find"  # type: ignore[index]  # JSON
    assert await provider.embed(["vpn"]) == [[0.1, 0.2]]


async def test_streaming_reads_server_sent_events() -> None:
    events = "".join(
        f"data: {json.dumps({'choices': [{'delta': {'content': piece}}]})}\n\n"
        for piece in ("Printer ", "jams.")
    )

    def handle(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text=events + "data: [DONE]\n\n")

    pieces = [p async for p in _provider(httpx.MockTransport(handle)).stream(REQUEST)]
    assert pieces == ["Printer ", "jams."]


async def test_a_failing_server_is_a_provider_error_that_never_carries_the_prompt() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503, text="overloaded")

    with pytest.raises(ProviderError) as raised:
        await _provider(httpx.MockTransport(handle)).chat(REQUEST)
    assert "printer" not in str(raised.value).lower()


# D-131: the model is swappable by configuration alone. These are the documented non-Qwen
# alternatives (docs/guides/ai-models.md); any name the server knows works the same way.
ALT_CHAT = "mistral-small-3.1-24b-instruct"
ALT_EMBED = "multilingual-e5-large"


async def test_another_configured_model_flows_through_with_no_code_change() -> None:
    settings = make_settings(
        ai_provider="openai_compatible",
        ai_base_url="http://model.local/v1",
        ai_model=ALT_CHAT,
        ai_embedding_model=ALT_EMBED,
    )
    built = provider_from(settings)
    assert isinstance(built, OpenAICompatibleProvider)
    assert (built.model, built.embedding_model) == (ALT_CHAT, ALT_EMBED)
    sent: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content)["model"])
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.3]}]})
        return httpx.Response(
            200, json={"model": ALT_CHAT, "choices": [{"message": {"content": "Hi."}}]}
        )

    provider = OpenAICompatibleProvider(
        "http://model.local/v1",
        settings.ai_model,
        settings.ai_embedding_model,
        api_key=None,
        external=False,
        timeout=5,
        transport=httpx.MockTransport(handle),
    )
    assert (await provider.chat(REQUEST)).model == ALT_CHAT
    await provider.embed(["vpn"])
    assert sent == [ALT_CHAT, ALT_EMBED]
    # The fake (CI, this Mac) carries the configured name too.
    fake = provider_from(make_settings(ai_model=ALT_CHAT))
    assert (await fake.chat(REQUEST)).model == ALT_CHAT
