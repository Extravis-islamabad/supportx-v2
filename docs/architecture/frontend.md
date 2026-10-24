# Frontend foundation

How the console and portal are built (architecture.md §9; WP-010; D-013, D-026). Read this before
adding a screen.

## Packages

| Package | What it gives you |
|---|---|
| `@supportx/api-client` | Typed client on the generated `schema.ts` (openapi-fetch), `ApiError`, query keys, hooks (`useSession`, `useSwitchTenant`, `useEntitlements`, `useUsers`, `useUser`, `useUpdateUser`). Test helpers under `@supportx/api-client/testing`. |
| `@supportx/labels` | All on-screen text: en/ar/ur resources on i18next + react-i18next, `label()`, `useLabels()`, plurals, interpolation, `humanize()` fallback with a missing-label warning. |
| `@supportx/ui` | Theme (light/dark/high contrast, Extravis purple `#9619B5`, tenant overrides), app shell, header, command palette, licence banners, `WriteButton`, error reporting, conflict dialog, reconnecting banner, error boundary. |
| `@supportx/forms` | React Hook Form + Zod; `FormField` (label + control + translated inline error); `applyServerErrors()` puts RFC 9457 field errors under the right field. |
| `@supportx/charts` | `<Chart>`: ECharts (tree-shaken core) with theme colours and RTL mirroring. |
| `@supportx/eslint-plugin` | `supportx/no-raw-enum`, `supportx/no-literal-text`. |

## Calling the API

```ts
const users = useUsers({ filter: allOf(searchFilter(q), { field: 'status', op: 'eq', value: 'active' }), sort: '-last_login_at' });
const user = await call(api.GET('/api/v1/users/{user_id}', { params: { path: { user_id } } }));
```

Paths, parameters and bodies are typed from the OpenAPI contract: a backend change that breaks
the UI breaks `tsc`. The client adds, without any screen code:

- `X-Request-ID` on every call (the "Copy reference" value when something fails);
- the CSRF header on POST/PUT/PATCH/DELETE (token from `/auth/me`, memory only);
- `Idempotency-Key` on POST unless you pass one (pass the same key when retrying an action);
- `If-Match` on PUT/PATCH/DELETE from the last ETag seen for that path, unless you pass one.
  Edit forms pass the version they were loaded from explicitly, so a background refetch can
  never turn a stale save into a silent overwrite.

Every failure is an `ApiError` (`status`, `kind: network | server | client`, `code`, `messageKey`,
`params`, `fieldErrors`, `requestId`, `isConflict`, `isEntitlement`, `isOutage`).

**Query keys:** `[resource, scope, ...params]`, e.g. `['users', 'list', query]`,
`['users', 'detail', id]` (`queryKeys` in api-client). Realtime (WP-011) will patch the cache by
the same keys.

## Text: labels, never codes

- Every visible string is a label key: `t('users.title')`, `t(`user_status.${user.status}`)`.
- Plurals: `t('users.total', { count })` with `_one`/`_other` (Arabic: `_zero` … `_many`).
- ESLint fails on raw codes in JSX (`{user.status}`, `title={ticket.priority}`) and on hard-coded
  words in JSX text or visible attributes (`placeholder="Search"`).
- CI (backend tests) fails when an error code, event type, licence catalogue code or **any enum in
  the OpenAPI contract** has no English or Arabic label (`tests/test_enum_labels.py` maps each
  contract enum to its label prefix; a new enum must be added there).

## Dates and rich text

- Show instants only through `useDateTime()` (`format`, `relative`): profile time zone, UI
  language, one source for absolute and relative times (REQ-WI-014). Enter them with
  `DateTimeField` (D-035).
- Rich text: `RichTextField` (Tiptap, lazy-loaded chunk) to edit, `RichTextView` to show. The
  value is HTML; the server sanitises every stored value (`app/shared/richtext.py`, nh3) against
  the same allow-list the editor produces, and is the security boundary (D-036, D-051).
- People in pickers always show their email as a second line, so equal names stay
  distinguishable (Area 15 lesson). Every option carries an `aria-label` (its label, never a
  code or ID: Ant Design's hidden accessibility list falls back to the value otherwise).
- Text people typed (subjects, reasons, names in headings) is wrapped in `<bdi dir="auto">`
  and typed into `dir="auto"` inputs, so it reads in its own direction in an RTL interface.
- Writes on a record go out once: the incident hooks join a second click to the write already
  on its way (`useSingleFlight`), and dialogs disable their buttons while pending.
- The UI language is a stored user preference (`ui_locale`, like the navigation layout); the
  theme sets fonts per language (Arabic in a Naskh face, Urdu in Nastaliq with taller lines).

## Theme and branding

`buildTheme(mode, branding)` in `packages/ui/src/theme.ts`. Modes: light, dark, high contrast
(black text and borders, thicker lines, darker primary). Secondary text is darker than Ant
Design's default so it meets WCAG AA. The user's choice is remembered in the browser; the first
visit follows the OS (`prefers-color-scheme`, `prefers-contrast`). `AppearanceProvider` accepts
`branding={{ colorPrimary, logoUrl }}`: WP-017 will load it per tenant; nothing else changes.

## Shell and entitlements

Console: sidebar (collapsible; mirrors in RTL), header (Ctrl+K palette, appearance, tenant
switcher, user menu), banners, page. Routes are lazy (one chunk per page); `/dev/components`
exists only in development builds.

What the plan allows comes from `GET /api/v1/entitlements` (`useLicence()`); the server enforces
everything again:

- Sections outside the plan are **hidden** for most users and **shown locked with an upgrade
  hint for tenant admins** (they can act on it; for others it is only noise). Opening a locked
  section explains it instead of showing the module.
- Grace period: a dismissible banner for tenant admins with the days left.
- Read-only: a persistent banner for everyone (viewing and export still work); every
  `WriteButton` is disabled with a tooltip.

## Errors

- Queries and mutations report failures through the app's QueryClient (`createQueryClient`):
  a translated notification with "Copy reference". Screens that show an error themselves set
  `meta: { silent: true }`.
- Forms: `applyServerErrors()` → inline under the field; 409 `version_conflict` →
  `ConflictDialog` ("Reload their version" / "Keep my changes", which re-applies only the fields
  you changed on top of the latest version); saves send only changed fields.
- 403 `entitlement_required` / `read_only_mode` / `technician_limit_reached`: their own
  translated explanations (feature name, licence reason).
- Outage (no answer, 502/503/504): one notification and a "Reconnecting…" banner that probes
  `/health` every 3 s and clears itself, then refetches.
- Render crashes: `ErrorBoundary` / route `errorElement` show a friendly page with a reference;
  details go to the browser console only.

## Bundles

Route-level lazy loading plus vendor groups (`frontend/vite.chunks.ts`): React, Ant Design (core,
data components, sub-packages), i18n, data, forms and ECharts are separate long-lived chunks; no
chunk exceeds 500 kB.

## Tests

Vitest with the fake API (`fakeApi` route table, records every call); Playwright against the dev
stack with axe (`frontend/e2e/README.md`).
