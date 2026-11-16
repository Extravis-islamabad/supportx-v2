### 2026-11-14 — Lane B: directory sync never touches an erased person (D-171, ADR-052)

Found while planning the erasure follow-ups: an erased person keeps their `directory_people`
link, so the next LDAP or Entra sync would write the directory's name and address back onto the
erased row (re-identification) and reactivate them while the directory still has them enabled.
Not live (approval is refused until the report is complete), but it had to close before approval
unlocks. Approved by the coordinator (plan B), with the approval gate lifted by this PR.

- identity_access (`service/directory_people.py`): `sync_directory_person` raises `ErasedPerson`
  for an erased linked person, before writing anything; `directory_returner` and
  `directory_leaver` do nothing for one (`LeaverOutcome.ERASED`); `_adoptable` never adopts an
  erased row.
- integrations (`service/directory_sync.py`, lane A reviews): the run counts them skipped with
  `SkipReason.ERASED` (`directory_skip.person_erased`, en/ar/ur), in the person and manager
  passes; the sync call and its refusals moved into `_synced` (complexity).
- The link stays: it keeps the directory from making them anew. An admin who removes it lets the
  next sync make a fresh person.
- Test (`tests/db/test_directory_sync.py`): after erasure, a rename-and-enable in the directory
  and then a removal change nothing on the row, nobody adopts their address, and the run counts
  the skip.
