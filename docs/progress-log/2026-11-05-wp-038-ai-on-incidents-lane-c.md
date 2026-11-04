### 2026-11-05 — WP-038: AI on incidents (lane C)

- **Conversation summary (REQ-INC-137, #207):**
  - The incident's panel opens with it: Summarise or Refresh, the model and the time, tags for
    out of date and for private notes, and a mark that it is AI-written.
  - Made through the gateway (`conversation_summary`).
  - Admins choose its sources in Admin › AI. Private notes are read only when chosen, and those
    summaries are shown only to staff. The two levels never mix.
  - A newer reply or note marks it stale, live on the record channel.
  - Erasing a person deletes the tenant's summaries, audited.
  - Migration 0069 adds `ai_summaries` and `summary_sources`.
- **Possible duplicates (REQ-INC-022, D-134, #207):** a panel beside the new-incident form.
  - AI on: open incidents the person may see, by meaning (`Gateway.similar`).
  - AI off: by subject with `pg_trgm`, and no model at all.
  - The same requester within the hour counts extra.
  - Incidents are embedded masked as calls are (subject and description only, never notes),
    only while AI is on. They are purged when it is switched off and backfilled when it is
    switched back on.
- **Writing help (REQ-INC-136):** in the reply and note editors.
  - Draft from an instruction, or improve the typed text: correct, shorter, longer, formal,
    friendly, or translated between English, Arabic and Urdu.
  - Reviewed before Insert or Replace; nothing is sent from it. The outcome is recorded.
  - A reply never reads private notes.
  - The rules (app.modules.ai.domain.prompts) forbid promises, times and numbers not in the
    record.
- **Eval:** `make ai-eval` gains invented-commitment cases in English and Arabic. Qwen3-4B Q4_K_M
  keeps to the record in 3 of 4; the miss is recorded in docs/guides/ai-models.md.
- **Tests:**
  - DB tests for summaries, duplicates and writing help.
  - Console unit tests.
  - `ai-incidents.spec`: the three features against the recorded fake, with axe and Arabic RTL.
- **Reviews:** lane A reviewed the work_items and incident-screen parts. All five of its points
  are fixed (duplicates by POST, the indexed trigram operator, ToneTag, `<bdi>`, the injected
  clock).
- **Proposed CLAUDE.md §3 line** (needs Haider's word in lane C's window): "**Approved additions
  (D-134):** PostgreSQL's pg_trgm extension (trigram similarity; created by migration 0020)."
