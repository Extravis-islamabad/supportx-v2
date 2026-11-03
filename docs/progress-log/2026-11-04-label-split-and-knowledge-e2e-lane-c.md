### 2026-11-04 — Labels in one folder per module; knowledge e2e fixes (lane C, D-127)

- `packages/labels/src/resources/<module>/{en,ar,ur}.ts`: 16 modules plus `shared` and `errors`.
  `en.ts`, `ar.ts` and `ur.ts` spread them into the same dictionaries; the server-side export is
  byte-identical (checked from a clean `make generated`). New labels go in the owning module's
  file (README.md has the prefix table). A test refuses a key in two modules, or in different
  modules per language. Urdu may miss only the frozen list `ur-missing.json` (369 older keys,
  shrink-only; translate, then delete the line).
- knowledge.spec 139 and 276 (red on main): saving a new article asked "Leave without saving?"
  and stayed on the new-article page. The leave guard read the dirty flag of the render before
  the save; it now reads a live flag the save sets. A console test covers it (it fails without
  the fix).
- knowledge.spec 347: since D-124 the record panel's Knowledge card has its own picker, so the
  spec targets the reply editor's. Its earlier timeout on main, from before the D-124 layout,
  could not be reproduced locally (the shared stack is off-limits for e2e); the stack smoke on
  this PR decides.
- knowledge.spec 206: the two axe findings were the old admin section tabs and their overflow
  menu, replaced by #159's section links.
