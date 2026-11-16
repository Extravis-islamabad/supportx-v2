### 2026-11-13 — WP-046a S6: mail channels (lane A)

PR #485, migration 0159. Lane B blocked and reviewed every mail-facing part in steps.

- Sender verification (`app/shared/mail/domain/sender_check.py`): Authentication-Results from
  the mailbox's trusted servers only, the topmost; a lower trusted header that disagrees spoils
  it; one From; DMARC or SPF with aligned DKIM, no Public Suffix List; any doubt is not verified.
  Lane B found a fail-open in quoted values in the first version; fixed with one quote-aware
  tokenizer and their four cases as tests.
- Mail commands (REQ-INC-025), block rules and quarantine (REQ-INC-026), people kept informed
  with a stop link (REQ-INC-066). The public-link guard of action links moved, unchanged, to
  `app/shared/api/public_links.py` for both public links (its own commit).
- Coordinator decisions: no new right for mail commands; a spoofing guard; quarantine 14 days;
  CC replies held for review (decision for Haider if needed). Lane B's #487 adds the asset side
  of REQ-INC-015 AC3.
- Follow-ups: editing the kept-informed list from the portal; configuration items on incidents
  (with CMDB, WP-053).
