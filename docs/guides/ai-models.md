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

The quantisation used and the quality measured with the eval set at that quantisation are
recorded here when WP-037 session 2 (local runtime) is done.

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
