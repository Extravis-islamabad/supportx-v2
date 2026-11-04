"""`make ai-eval` scores retrieval and answers from what the server returns (no model here)."""

import json

import httpx
import pytest

from tooling import ai_eval

DATA = {
    "documents": {"vpn": "vpn text", "printer": "printer text"},
    "queries": [
        {"q": "vpn?", "lang": "en", "expect": "vpn"},
        {"q": "طابعة؟", "lang": "ar", "expect": "printer"},
    ],
    "answers": [
        {"lang": "en", "prompt": "Summarise."},
        {"lang": "ar", "prompt": "لخّص."},
    ],
}
# Each text's vector: documents first, then queries (the order the eval sends them in).
VECTORS = {
    "vpn text": [1.0, 0.0],
    "printer text": [0.0, 1.0],
    "vpn?": [0.9, 0.1],
    "طابعة؟": [0.8, 0.2],  # nearer the VPN article: a top-1 miss, still in the top 3
}


def _server(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if request.url.path.endswith("/embeddings"):
        return httpx.Response(
            200, json={"data": [{"embedding": VECTORS[text]} for text in body["input"]]}
        )
    prompt = body["messages"][0]["content"]
    answer = "The VPN drops hourly." if prompt == "Summarise." else "<think>x</think> نعم"
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": answer}}], "usage": {"completion_tokens": 5}},
    )


def test_retrieval_and_answers_are_scored() -> None:
    with httpx.Client(transport=httpx.MockTransport(_server)) as client:
        scores = ai_eval.retrieval(client, "http://m/v1", "bge-m3", DATA)
        answers = ai_eval.answers(client, "http://m/v1", "qwen3-4b", DATA)
    assert scores["en"] == {"queries": 1, "top1": 1.0, "top3": 1.0, "dimension": 2}
    assert (scores["ar"]["top1"], scores["ar"]["top3"]) == (0.0, 1.0)
    assert [a["ok"] for a in answers] == [True, False]  # reasoning text in the answer fails


def test_without_a_server_configured_it_says_how_to_start_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ai_eval, "_env", dict)
    assert ai_eval.main() == 1
    assert "make ai-dev-model" in capsys.readouterr().err


def test_invented_promises_times_and_numbers_are_caught() -> None:
    record = "The VPN drops every hour since Monday. Ticket 42."
    assert ai_eval.invented("We are looking into the VPN drops.", record) == []
    assert ai_eval.invented("It drops every hour since Monday (ticket 42).", record) == []
    assert ai_eval.invented("We will fix it by Friday.", record) == ["We will", "Friday"]
    assert ai_eval.invented("Expect it within 3 days.", record) == ["within", "days", "3"]
    assert ai_eval.invented("سيتم حل المشكلة غدًا", "") == ["سيتم", "غدًا"]
    assert ai_eval.invented("الشبكة ستُحل في أقرب وقت ممكن", "") == ["ستُ", "في أقرب وقت"]


def test_commitment_answers_are_scored() -> None:
    data = {"commitments": [{"lang": "en", "record": "VPN drops.", "instruction": "When?"}]}

    def server(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "It will be fixed tomorrow."}}]}
        )

    with httpx.Client(transport=httpx.MockTransport(server)) as client:
        (result,) = ai_eval.commitments(client, "http://m/v1", "qwen3-4b", data)
    assert result["ok"] is False
    assert result["invented"] == ["will be fixed", "tomorrow"]
