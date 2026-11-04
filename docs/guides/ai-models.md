# AI models: choosing, swapping, retention

SupportX's AI features (reply drafts, text improvement, conversation summaries; WP-037/038) talk
to one model server through the AI gateway. The model is chosen by configuration, never by
code (D-131).

## Configuration

| Setting | Meaning |
|---|---|
| `SUPPORTX_AI_PROVIDER` | `openai_compatible` (a vLLM or llama.cpp server, or any server speaking that API), or `fake` (recorded answers: CI and development) |
| `SUPPORTX_AI_BASE_URL` | The server, e.g. `http://vllm:8000/v1` |
| `SUPPORTX_AI_MODEL` | The chat model name the server knows |
| `SUPPORTX_AI_EMBEDDING_MODEL` | The embeddings model name |
| `SUPPORTX_AI_PROVIDER_EXTERNAL` | `true` when the server is outside the installation: personal data is then always masked |

Changing a model is a configuration change and a restart. The gateway, the call log and the
screens show whichever name is configured.

## Approved models (D-131)

| Role | Default | Licence | Runtime |
|---|---|---|---|
| Chat | Qwen3-14B, quantised to fit one 24 GB GPU | Apache-2.0 | vLLM |
| Small chat (development, small sites) | Qwen3-4B | Apache-2.0 | llama.cpp server |
| Embeddings | bge-m3 | MIT | vLLM or llama.cpp server |

### Quantisation and quality (eval set)

`make ai-eval` runs the eval set (`backend/tooling/ai_eval_set.json`) against the configured
servers:
- **Retrieval:** 20 queries in English, Arabic and Urdu over ten support articles. Is the right
  article the nearest (top 1), or among the three nearest (top 3)?
- **Answers:** six prompts (summaries and reply drafts) answered in their own language, with no
  reasoning text in the answer.

Run it for every model and quantisation before offering it.

| Model, quantisation | Measured | Retrieval top 1 (en / ar / ur) | Retrieval top 3 | Answers in the right language | Speed |
|---|---|---|---|---|---|
| bge-m3 Q8_0 (llama.cpp server, Metal) | 2026-11-04 | 6/6 · 8/8 · 5/6 | 20/20 | (embeddings) | |
| Qwen3-4B Q4_K_M (llama.cpp server, Metal, Apple M5) | 2026-11-04 | | | 6/6 | 1–6 s per answer, ~18–29 tokens/s |
| Qwen3-14B Q4_K_M (demo, one 24 GB GPU) | at the first demo switch | | | | |

The Urdu miss in top 1 found the right article second. Every query found it in the top 3.

### Embedding width

The embedding store holds 1024-wide vectors, the width of both approved embedding models. A
model of another width is refused until a migration widens the column. Every vector records its
model. After a model change, an hourly job re-embeds the old rows, and searches never mix two
models' vectors (D-131).

## Deployment (Helm chart)

The chart's `ai` values run the models next to SupportX. The chart default is off; the installer
switches it on (WP-014c).

| Component | Model | Runs on |
|---|---|---|
| `llm-cpu` | Qwen3-4B Q4_K_M, llama.cpp server | CPU only, in every install |
| `llm-embed` | bge-m3 Q8_0, llama.cpp server | CPU |
| `llm-gpu` (optional, `ai.gpu.enabled`) | Qwen3-14B AWQ, vLLM | One GPU node; it answers chat instead of `llm-cpu` |

- **Weights:**
  - Each model has its own volume. Its weight files are pinned by repository revision and
    sha256 in `values.yaml`, and checked before the server starts; a mismatch stops the pod.
  - Connected installs fetch missing files from `ai.mirror`, Hugging Face by default.
  - Air-gapped installs set `ai.mirror: ""`, and the installer fills the volumes. A pre-loaded
    volume is never downloaded again.
  - With the egress allow-list on, list your mirror or proxy under
    `networkPolicies.egress.components.llm-cpu` (and `llm-embed`, `llm-gpu`).
- **GPU node:**
  - Set `ai.gpu.resourceName` to your device plugin's resource (for example `nvidia.com/gpu`),
    plus `ai.gpu.nodeSelector` and `ai.gpu.tolerations`. Nothing vendor-specific is assumed.
  - One copy, so no disruption budget: draining the node pauses chat, and AI features answer
    "unavailable" meanwhile.
- **Network:** only the API and the consumers worker reach the model servers.

To use another model, change its `name`, `repo`, `revision` and `files` (with their sha256).
Embedding models must be 1024 wide.

## Alternatives that are not of Chinese origin

Some customers, often government and banks, do not accept a model of Chinese origin. Qwen
(Alibaba) and bge-m3 (BAAI) both are. These alternatives work with the same configuration; only
the model names (and the weights on the server) change:

| Role | Alternative | Origin, licence | Notes |
|---|---|---|---|
| Chat | Mistral Small 3.1 24B Instruct (`mistral-small-3.1-24b-instruct`) | Mistral AI (France), Apache-2.0 | Multilingual, including Arabic; fits one 24 GB GPU quantised |
| Embeddings | multilingual-e5-large (`multilingual-e5-large`) | Microsoft, MIT | Multilingual, including Arabic and Urdu |

Run the eval set against an alternative before offering it to a customer, as for the default.

## Retention and training

- AI conversation text (what was sent to the model, masked, and what it answered) is kept for
  30 days by default. An admin changes the period in Admin › AI settings.
- After the period, a daily job deletes the text. Who used which feature, when and with what
  outcome stays for reports.
- Erasing a person also deletes the text of their AI conversations.
- Every deletion is recorded in the audit log: the retention purge (with the number of
  conversations and the period applied) and erasure.
- **AI conversations are never used to train any model.** No data leaves the installation for
  training, and the local models are not fine-tuned on customer data.

## Developer machines and CI

Never run a large model in Docker on a developer Mac: use the small native model (Qwen3-4B with
the llama.cpp server) or the recorded fake. CI always uses the recorded fake.
