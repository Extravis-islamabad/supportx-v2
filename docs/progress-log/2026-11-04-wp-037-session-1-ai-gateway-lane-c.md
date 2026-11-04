### 2026-11-04 — WP-037 session 1: the AI gateway, with the recorded fake (lane C)

- New `ai` module (architecture.md §12) with its layers contract, and a contract keeping core,
  shared, workers and tooling away from the model providers. Every AI call goes through
  `Gateway`. The checks run in this order: the caller's permission for the feature; the plan
  (`has_feature("ai_assist")`, the entitlement interface only); the master and feature
  switches; masking; the provider; the call log.
- The log entry is written in its own transaction, so refusals and failures are kept even when
  the caller's work rolls back.
- Providers: one interface (chat, completion, embeddings, tools, streaming). `FakeProvider`
  replays recorded answers or answers deterministically; CI, tests and laptops use it (product
  owner: never a large model in Docker on a developer Mac). `OpenAICompatibleProvider` is plain
  `httpx`, for vLLM or the llama.cpp server in session 2. No new packages.
- Masking: always for an external provider, optional for the local model. It covers e-mail
  addresses, phone numbers, IPv4 and IPv6 addresses, Luhn-checked card numbers, regional
  national IDs, and the record's known names. Placeholders are stable within a call and
  restored for the person; a stream never shows half a placeholder. The log keeps the masked
  text only.
- `ai_settings` (RLS, If-Match, history, audit `ai.settings_changed`, outbox
  `ai.settings.changed`, live to every screen) and `ai_calls` (RLS; the app role may select,
  insert and update, never delete). A daily job clears call text after the tenant's retention
  period (30 days by default, product owner to confirm) and keeps the row. Migration 0060.
- Admin › AI: the master switch, a switch per feature grouped by area (switching off asks
  first and says what happens to existing results), masking for the local model, the
  retention period, and which model answers. Labels in a new `ai` label module (en, ar, ur).
- D-131 (the product owner's AI decisions, 2026-11-04):
  - Approved: vLLM, the llama.cpp server, Qwen3-14B (quantised to one 24 GB GPU), Qwen3-4B and
    bge-m3.
  - Models are swappable by configuration only. docs/guides/ai-models.md names non-Chinese
    alternatives: Mistral Small 3.1 24B for chat, multilingual-e5-large for embeddings. Tests
    prove a differently configured model name is called, answers and is logged.
  - Retention: 30 days by default, set per tenant. AI conversations are never used for
    training; the AI settings screen and the guide both say so.
  - Every deletion is audited (`ai.calls_purged` with count and period, `ai.calls_erased`). The
    purge runs in batches of 1,000, so no statement grows with a backlog.
- Not yet: quotas (REQ-AI-030, V1). Session 2 (local runtime, embeddings, retrieval) is
  unblocked by D-131 and starts once #188 lands. It records the quantisation and the eval-set
  quality at that quantisation.
