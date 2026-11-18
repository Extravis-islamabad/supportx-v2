### 2026-11-17 — The CMDB mentions port and snapshot redaction (lane B, 0176)

**Why:** #524 puts `cmdb` in REQUIRED_MENTION_PORTS, so every erasure approval waited for this port. The design is in plans/cmdb-mentions-port-0176-lane-b.md, with lane C's six conditions.

**The port, two record types:**
- `ci`: the CI's name and description now, binned CIs included.
- `ci_version`: each saved snapshot's name and description, so an old name is found after a rename.

**Redaction:**
- A CI is redacted through an ordinary save: version, history naming the field only with reason `erasure_redaction`, a new snapshot, and `CiUpdated`.
- A snapshot is redacted through the migrator-owned `cmdb_redact_version(mention, value)`, bound to an open, redacted `ci_version` mention of the caller's tenant. It accepts only the old text with stretches replaced by the marker (0168's `kb_redaction_kept`), and writes one key.
- An unrelated older name stays as it was.

**Passage:** for someone who may see the CI. Binned CIs, and their snapshots, are shown only to `people.erase` holders, the 0170 rule, because the registry redacts only what the redactor can read.

**Erasure readiness:** `PENDING_MENTIONS` is now empty: every required mentions port is real.

**Tests:**
- `tests/db/test_cmdb_mentions.py` (2): the journey, including a renamed CI, a binned CI, the event payload, and a second run as a no-op. Also the definer: not redacted, another tenant, a non-pure value, the app role's UPDATE refused, a closed erasure.
- The approval test with every real port.
- The mentions guard (20).
- The migration guard (13).

**Not in this PR:** CI custom text values, which join with 0175.
