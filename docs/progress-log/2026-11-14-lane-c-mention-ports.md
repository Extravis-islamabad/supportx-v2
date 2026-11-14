### 2026-11-14 — Lane C: knowledge and announcements mentions ports (ADR-052 S2, migration 0168)

The plan was approved by the coordinator on 2026-11-14 (topics in, type names out, old versions
redacted too, search and AI rebuilt). Lane B's conditions for the definer function apply. Lane B
blocks.

## Built

- **Migration 0168:**
  - `kb_redaction_kept(old, new)`: true only when `new` is `old` with non-empty stretches
    replaced by the marker.
  - `kb_redact_version(mention, value, keywords)`: migrator-owned and bound like 0164. Its rules:
    - a redacted mention with redactor and time;
    - an erasure in requested or approved;
    - record type `kb_article_version`;
    - the field taken from the mention (title, body_html or keywords);
    - the tenant taken from `app.tenant_id`;
    - false when nothing changes.
  - It sets `supportx.kb_redaction` to the row, updates the field, and clears the flag on every
    way out.
  - The freeze (`kb_versions_frozen`) lets a change through only as that function's owner with
    the flag naming that row. The app role is refused even with the flag; the migrator is refused
    without it. The downgrade restores 0036's freeze.
- **`knowledge/service/person_mentions.py`:**
  - phases: versions, votes (others'), articles (withdrawal reason), topics (names, description);
  - frozen fields go through `kb_redact_version`, the rest are plain updates;
  - every redaction writes history naming the field (reason `erasure_redaction`), bumps the
    version and raises KbArticleSaved or KbTopicSaved;
  - a value too long is refused (`erasure_redaction_too_long`);
  - passages follow `get_article`: internal and reject notes only for editors, superseded
    versions only for editors, feedback for the article's editors, topics for staff.
- **`announcements/service/person_mentions.py`:** title and body (plain text), with the same
  history, event and too-long rules; passage through `get_announcement`.
- **Labels en/ar/ur:** `audit.object.kb_article_version`, `kb_vote`, `kb_topic`, `announcement`.
- **Search** reads the computed `search_vector`, so it follows the redaction by itself. There are
  no AI embeddings of knowledge articles today (only incidents), so there is nothing to drop; a
  KB embedding source, when one comes, would hear KbArticleSaved.

## Tests

- `tests/db/test_kb_version_redaction.py` (3):
  - the marker check (arbitrary text, an added or changed character, no marker, keywords);
  - the binding (another field, no redactor, tenant B, a closed erasure);
  - the freeze (the app role even with the flag; the migrator right after the function, in
    the same transaction).
- `tests/db/test_mention_ports_lane_c.py`:
  - every place found, never with text;
  - an editor's passage;
  - the too-long refusal;
  - the redaction of a published version and of the other fields;
  - history and events;
  - search no longer finds the name;
  - a second redaction changes nothing.
