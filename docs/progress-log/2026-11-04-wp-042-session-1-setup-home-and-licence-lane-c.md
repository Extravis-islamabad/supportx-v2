### 2026-11-04 — WP-042 session 1: setup home, setup menu and search, licence page (lane C)

- The setup map (`pages/admin/setupMap.ts`) lists every setup page once: group, name,
  permission. A test checks that every admin route is in it, once, with its labels.
- `/admin` is the setup home: the pages this person may open, grouped by task (people and
  access, service desk, automation and SLA, channels, organisation, licence, audit), each with
  a one-line explanation. A search finds a page by name, explanation, keywords or synonyms in
  en, ar and ur, folding case, punctuation and Arabic letter forms. Coming back to the home
  returns to where it was scrolled.
- A grouped setup menu (a `<nav>` of links, `aria-current` on the open page) replaces the
  section bar, beside the page from 992 px and above it on smaller screens. The test ids
  `admin-sections-<key>` are kept. Setup pages are also in the command palette, found by
  keyword once something is typed.
- Licence and plan (`/admin/licence`, `licence.manage`): edition, state, term, grace,
  features, and limits with usage, read through the entitlement interface only. Usage is live:
  licensing sends `entitlements.usage_changed` (a tenant-wide signal, no IDs) when an identity
  event can change who counts as a technician. This reuses the identity events already in the
  outbox rather than adding a second event.
- Labels in the `shared` and `licensing` module files (D-127). An e2e spec covers axe in light,
  dark and Arabic at 1366 and 390 px.
