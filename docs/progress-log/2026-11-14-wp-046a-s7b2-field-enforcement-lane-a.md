### 2026-11-14 — WP-046a S7 slice b2: field access in search, live signals, designers (lane A)

- **Search (§6):** `identity_access.restricted_fields`; `_custom_text` leaves restricted custom
  values out; `service/search_rebuild.py`: a consumer marks the type on a custom field's rule
  change, a 60 s schedule rebuilds its search text in committed pages and clears the mark only
  if no newer change arrived; search rechecks matches without the custom text while marked.
- **Live and conflicts (§7):** staff publications and 409 `changed_fields` say "restricted".
- **Designers (§8):** rules and triggers (author passed by the routes), workflows (a problem on
  the step, `node:<id>`, publishing refused) and template defaults refuse a field the author does
  not see in clear: 422 `field_not_permitted` (labelled en/ar/ur).
- **Tests:** search before, during and after a rebuild; live signal and 409 naming; designer
  refusals (db and pure); the AI gateway never sees a restricted value; the variables guard.
- **Waiting on lane C:** `open_custom` and the AUD-017 view hook (no signatures yet).
