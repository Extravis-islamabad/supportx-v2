# @supportx/labels

Every text the UI shows comes from here (CLAUDE.md rule d); the server reads the same dictionary
from `backend/app/shared/labels/resources.json` (`make labels-json`).

## Directional isolates

**Rule:** a filled string value is wrapped in FSI…PDI (U+2068…U+2069) when the sentence is
right-to-left (ar, ur) or the value contains right-to-left letters (bidi class R or AL), except
`count`, numbers, display IDs and tokens (`INC-12`, `[INC-12]`), values already isolated, and a
label that is nothing but the one placeholder.

- `isolation-cases.json` is the contract: the console (`isolation.test.ts`) and the server
  (`backend/tests/test_label_isolation.py`) both run every case in it.
- Text that leaves the screen carries no marks: mail subjects, plain-text mail and exported files
  use `plain_label` on the server; HTML mail uses `html_label`, which isolates with `<bdi>`.
- Search, pickers and the mail token parser strip pasted marks (`stripIsolates` /
  `strip_isolates`).
- `useLabelsIn` returns plain text, because it builds stored names.
- `rtl-ranges.json` is generated from Python's Unicode data by `backend/tooling/rtl_ranges.py`
  (`make labels-json`).
