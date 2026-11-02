### 2026-11-02 — WP-033 session 3b: approval inbox, knowledge settings, the e2e round (lane C)

- Built to D-120 (plan ~/Desktop/wp-033-s3b-plan.md), stacked on 3a (`feat/wp-033-s3b` on
  `feat/wp-033-s3a`), draft #151.
- Backend:
  - `prefix_problems` moved to `app/shared/domain` with its test (lane A agreed). Same rule and
    code; work_items imports it from there.
  - Articles count on their own counter `KB_ARTICLE`. Session 1 counted by prefix, so a renamed
    prefix would have restarted at 1. Settings take the prefix and the next number, all or
    nothing and never backwards.
  - Article types: add (English and Arabic names required), change, retire and restore, with
    If-Match, audited (`knowledge.type_created`, `knowledge.type_changed`), with the
    `knowledge.type.saved` and `knowledge.settings.changed` events through the outbox. Every
    knowledge screen refetches on the tenant broadcast.
  - Self-approval is off by default (D-120 (4)).
  - Migration 0046 (expand only): `kb_types` version, `updated_at` and `updated_by`; the
    `KB_ARTICLE` counter starts from each tenant's KB counter or highest article number; the
    downgrade hands the count back to the prefix counter.
- Console:
  - **Approval inbox** `/knowledge/approvals`: the queue, and a preview of the version under review
    beside what readers see now ("first version" when nothing is published), the author's note
    and a title change called out. Approve and send back use the article page's buttons and
    reasons. An article decided elsewhere leaves live and says so. At 390 px the preview opens in
    a drawer.
  - **Admin › Knowledge**: self-approval, requester knowledge, prefix and next number (with the
    next ID), each with its default; article types table and dialog.
- Tests:
  - DB: numbering continues across a prefix change and back, never backwards, all or nothing;
    types (Arabic name required, built-in names fixed, retired types refused for new articles but
    kept on old ones, tenant isolation, audit and outbox); the 0046 migration up and down with
    existing article IDs kept.
  - Vitest: inbox and settings screens (10).
  - e2e `knowledge.spec.ts` (sessions 2, 3a and 3b, English and Arabic, axe at 1366 and 390 px):
    written, typechecked; runs in the batched QA round under the QA lock once #138 and #139 are
    on main.
- Not yet: the knowledge-manager role grants (wait for lane B's #131 on main); Arabic contrast
  measured directly (with lane A's contrast helper, #145) in the e2e round.
- List rows now carry `author_id` and `author_name` (who wrote the version shown), so the inbox
  queue says who wrote each article (coordinator, 2026-11-02).
- Follow-up (lane A's note on #138): knowledge DB tests reuse lane A's incident test world; a
  knowledge-owned fixture later.
