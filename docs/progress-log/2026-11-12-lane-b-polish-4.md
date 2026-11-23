### 2026-11-12 — Lane B polish 4: review follow-ups and QA minors F-15, F-17, V-15

- **Scope:** lane B's bundled polish round 4. No migration, no new dependency.
- **Fixed:**
  - Asset type tree: each row's accessible name joins the name and the count with the shared
    `list.separator` label, so Arabic and Urdu get "،" (`TypeTree.tsx`; test in `views.test.tsx`).
  - `roles.assign_role` and `_service_members` compare with `UserType.SERVICE.value`, not a
    `"service"` literal.
  - `test_urls.py`: `/?` and `/#` pass `safe_return_to` as they are and land on the UI's own home.
    Today's behaviour is safe, so the new test only pins it.
  - `playwright-in-image/run.sh`: every add-hosts entry has to be `host:ip` (an IPv4 address or
    `host-gateway`), or the script stops with an error that names the entry. Passes shellcheck
    0.10.0.
  - `assets/service/imports.py`: a comment at `Lookups(`. A dry run that resumes in a new worker
    reads the asset-limit slots again and loses the count from earlier slices. That only affects
    advice; the real run counts again under the limit's lock.
  - F-15: a consumable below its minimum now says "Below minimum". "At minimum" is kept for a
    stock exactly at its minimum. This covers the list, the stock table and the record tag. The
    unit cost is shown in the tenant's base currency. New labels have en, ar and ur text.
  - F-17: the asset record's breadcrumb and tab title now include the asset's name.
  - V-15: the audit progress bar fills by found ÷ expected, the same figure as the "1 of 6 found"
    text. The marked count is still in the bar's accessible name.
- **Skipped (already on main):**
  - AssetPage `copyable={asset.tag !== null}` (#345).
  - F-17 consumable breadcrumb (28c850e3) and the straight-line depreciation default
    (d3013d32, D-157).
- **Not done:** V-15's "clipped" matrix warnings on the audits screen were left alone. They are
  out of this round's scope, and the bar fix may change them.
