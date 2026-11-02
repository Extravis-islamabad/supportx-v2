### 2026-11-02 — WP-040 session 1: connector framework (lane B)

After the move to Extravis-islamabad: confirmed the merge queue on #147 (merge_group checks green,
merge commit 0242b48). #133/#134 failed because mail attachments are uploaded as the sender and a
requester could not attach to a record; lane A's #142 is the fix, merged into both (merge order:
#142 first). WP-040 session 1 built on `feat/wp-040-connectors` (draft #150): catalogue, secrets
store (0045), runs and health (0049), per-category set-up rights, Admin › Integrations. Service
identities moved to session 2. Migrations renumbered after lane A's 0044/0047 and lane C's
0046/0048. Reviewed lane C's `copy_to_drafts` for WP-033 s4 (7 conditions agreed). WP-013 plan
(private licence-core repo) sent to the product owner. Tests: area suites (backend 156, console
admin 152) green; full suite in CI.
