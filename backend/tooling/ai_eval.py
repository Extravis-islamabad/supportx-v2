"""`make ai-eval`: the WP-037 eval set against a running model server (never in CI).

Measures what docs/guides/ai-models.md records for each model and quantisation:

- Retrieval: for each query (English, Arabic, Urdu), is the right document the nearest (top 1)
  or among the three nearest (top 3)? Cosine similarity of the embedding model's vectors.
- Answers: each prompt answered in its own language (Arabic script for Arabic and Urdu), with
  no reasoning text in the answer, plus the time per answer and the speed in tokens per second.

It talks to the OpenAI-compatible API directly (tooling never imports the app's providers) at
SUPPORTX_AI_BASE_URL / SUPPORTX_AI_EMBEDDING_BASE_URL, models SUPPORTX_AI_MODEL /
SUPPORTX_AI_EMBEDDING_MODEL, as `make ai-dev-model` sets them in backend/.env.
"""

import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

SET = Path(__file__).with_name("ai_eval_set.json")
ARABIC_SCRIPT = re.compile(r"[؀-ۿ]")
LATIN = re.compile(r"[A-Za-z]")


def _env() -> dict[str, str]:
    """backend/.env, then the environment (which wins)."""
    values: dict[str, str] = {}
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    values.update(os.environ)
    return values


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1.0)


def retrieval(client: httpx.Client, url: str, model: str, data: dict[str, Any]) -> dict[str, Any]:
    """Top-1 and top-3 accuracy per language."""
    keys = list(data["documents"])
    texts = [data["documents"][k] for k in keys] + [q["q"] for q in data["queries"]]
    response = client.post(f"{url}/embeddings", json={"model": model, "input": texts})
    response.raise_for_status()
    vectors = [item["embedding"] for item in response.json()["data"]]
    docs, queries = vectors[: len(keys)], vectors[len(keys) :]
    per: dict[str, list[tuple[bool, bool]]] = {}
    for query, vector in zip(data["queries"], queries, strict=True):
        ranked = sorted(keys, key=lambda k: -_cosine(vector, docs[keys.index(k)]))
        per.setdefault(query["lang"], []).append(
            (ranked[0] == query["expect"], query["expect"] in ranked[:3])
        )
    return {
        lang: {
            "queries": len(rows),
            "top1": sum(r[0] for r in rows) / len(rows),
            "top3": sum(r[1] for r in rows) / len(rows),
            "dimension": len(docs[0]),
        }
        for lang, rows in per.items()
    }


def answers(
    client: httpx.Client, url: str, model: str, data: dict[str, Any]
) -> list[dict[str, Any]]:
    """Each prompt answered: in its language, no reasoning text, how fast."""
    out = []
    for item in data["answers"]:
        started = time.monotonic()
        response = client.post(
            f"{url}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": item["prompt"]}],
                "max_tokens": 200,
                "temperature": 0.2,
                # Qwen3: answer directly; the gateway's features ask the same way.
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        response.raise_for_status()
        body = response.json()
        text = (body["choices"][0]["message"].get("content") or "").strip()
        seconds = time.monotonic() - started
        tokens = (body.get("usage") or {}).get("completion_tokens") or 0
        arabic = len(ARABIC_SCRIPT.findall(text))
        latin = len(LATIN.findall(text))
        language_ok = arabic > latin if item["lang"] in {"ar", "ur"} else latin > arabic
        out.append(
            {
                "lang": item["lang"],
                "ok": bool(text) and language_ok and "<think>" not in text,
                "seconds": round(seconds, 1),
                "tokens_per_second": round(tokens / seconds, 1) if seconds else 0.0,
                "answer": text[:160],
            }
        )
    return out


def main() -> int:
    """Run the set and print the results as JSON."""
    env = _env()
    chat_url = env.get("SUPPORTX_AI_BASE_URL")
    if not chat_url:
        sys.stderr.write("No SUPPORTX_AI_BASE_URL: start a model first (make ai-dev-model).\n")
        return 1
    embed_url = env.get("SUPPORTX_AI_EMBEDDING_BASE_URL") or chat_url
    data = json.loads(SET.read_text(encoding="utf-8"))
    with httpx.Client(timeout=300) as client:
        result = {
            "chat_model": env.get("SUPPORTX_AI_MODEL"),
            "embedding_model": env.get("SUPPORTX_AI_EMBEDDING_MODEL"),
            "retrieval": retrieval(
                client, embed_url.rstrip("/"), env.get("SUPPORTX_AI_EMBEDDING_MODEL", ""), data
            ),
            "answers": answers(
                client, chat_url.rstrip("/"), env.get("SUPPORTX_AI_MODEL", ""), data
            ),
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
