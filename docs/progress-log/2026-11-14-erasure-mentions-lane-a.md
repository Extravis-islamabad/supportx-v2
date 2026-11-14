# 2026-11-14 — ADR-052 S2: lane A's mentions ports (lane A)

The `PersonMentions` contract from lane B's S1b (#506). Plan sent to lane B, approved with six
conditions, all applied.

- `work_items/service/person_mentions.py`: phases records, conversation, tasks, worklogs; plain
  and rich text matched with the shared helpers; the person's own requested records skip only
  the fields their erasure blanks.
- `work_items.redact_fields`: a redaction's save (history names the field, old/new None;
  `custom_text` recomputed; `work_item.updated` fires for search and the AI re-embedding).
- New event `work_items.conversation.redacted` (v1), routed like the other conversation events;
  label en/ar/ur; event schemas regenerated.
- `integrations/service/person_mentions.py`: `mail_fetched.subject`; `row_ref` names a ledger row
  by an md5 UUID of its key (an identity, not a secret).
- Tests: `tests/db/test_erasure_mentions_lane_a.py` (record text and custom field found,
  passage by rights, redacted, history and search; the requester's record and its note; tasks
  and worklogs; a hidden field has no passage; mail; 100k timing). Lane B's report test now
  expects work_items and integrations present.

Open: work-item redactions keep fingerprinted history rows until lane B's #511
(`redact_signed_history`), so approval refuses those erasures (`erasure_signed_history_kept`),
as lane B expects. A redaction of a mail row looks it up by a scan of the tenant's ledger
(`md5(key)`): fine for a rare admin action; an index can follow if needed.
