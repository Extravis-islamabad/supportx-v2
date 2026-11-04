### 2026-11-04 — WP-037 session 2: local runtime, embeddings and retrieval (lane C, in progress)

- **Native local model on a Mac** (product owner, 2026-11-04). Never Docker.
  - `make ai-dev-model`: Qwen3-4B Q4_K_M plus bge-m3 Q8_0, as two native llama.cpp servers
    (Metal), on 127.0.0.1:8081 and :8082.
  - `make ai-demo-model`: Qwen3-14B Q4_K_M. It warns about lane work and refuses below 12 GB
    free.
  - `make ai-model-stop`, `make ai-model-status`.
  - Only the `SUPPORTX_AI_*` lines of backend/.env change; a copy is kept once.
  - Documented in docs/dev-setup.md.
  - `SUPPORTX_AI_EMBEDDING_BASE_URL`: embeddings from their own server (one model per server).
- **Migration 0075, `ai_embeddings`** (number from the coordinator):
  - One 1024-wide pgvector per piece of a record, with its model and width; HNSW cosine index.
  - RLS (FORCE) and actor audit. No text is stored, only its hash.
- **The one embedding and retrieval service** (REQ-AI-057, 058), `Embeddings` on
  `app.state.ai_embeddings`:
  - `index` skips unchanged text.
  - `search` compares only the configured model's vectors, then keeps the records the person
    may see, asked of the owning module (REQ-AI-025).
  - `remove` forgets a record.
  - Text for an external provider is masked first.
- **Model swaps**:
  - Old rows are re-embedded by an hourly sweep through each module's registered text source
    (D-131 notes).
  - A model of another width is refused.
  - The fake now makes word-hashed 1024-wide vectors, so retrieval is testable without a model.
- **Eval set and `make ai-eval`**: retrieval in en/ar/ur, and answers in their own language.
  Measured on this Mac:
  - bge-m3 Q8_0: top 1 in 19 of 20 queries, top 3 in all 20.
  - Qwen3-4B Q4_K_M: 6/6 answers in the right language, ~18–29 tokens/s.
  - Recorded in docs/guides/ai-models.md and D-131. Qwen3-14B is measured at the first demo
    switch.
- **Still to do this WP:**
  - Deployment profiles (REQ-AI-003, 004): the llama.cpp server CPU-only in every install, and
    an optional GPU node with vLLM, in the Helm chart.
  - Retrieval calls logged through the gateway once a feature uses them (WP-038).
