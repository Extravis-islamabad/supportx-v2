# Console design

How every console screen is laid out (D-124). The design is our own, on Ant Design 5: never copy
another product's screens, wording, help text or icons (CLAUDE.md §2). The pieces live in
`frontend/packages/ui/src/layout/` and `frontend/packages/ui/src/density.ts`; use them rather
than building a header, toolbar or action row by hand.

## Density and tokens

The console runs Ant Design's `compactAlgorithm` on top of light, dark and high contrast
(`<AppearanceProvider density="compact">` in `apps/console/src/App.tsx`). The portal keeps the
default density.

| Token | Values | Use |
|---|---|---|
| `SPACE` | 4 · 8 · 12 · 16 · 24 · 32 (`xxs` … `xl`) | Every gap, margin and padding. Nothing in between. |
| `TYPE` | meta 12 · data 13 · body 14 · section 16 · record 18 · page 20 | Font sizes. Tables and dense lists use `data`. |
| `CONTROL_HEIGHT` | 28 px | Buttons, inputs, selects. |
| `ROW_HEIGHT` | 40 px | Table rows. |
| `PANEL_WIDTH` | 320 px | The record's properties panel. |

Urdu keeps its taller line height: rows grow rather than clip. Colours come from the theme
tokens only (`theme.useToken()`), so dark and high contrast follow.

## Page types

### List page

```
PageHeader    Title  (count)                                   [page actions, ≤ 3]
FilterBar     [View ▾] [Search ……………] [quick filters] [Filters (n)]          [Columns]
AlertStrip    (optional)
Table         40 px rows, small size, sticky header, ellipsis with tooltip
```

- `ListPage` takes `header`, `kpis`, `filters`, `alerts` and the table as children.
- `FilterBar` holds the view picker, the search, at most a few quick filters, the "Filters (n)"
  button and end-side controls such as columns. Put controls straight in the bar, not in a
  wrapping box of their own: a browser sizes such a box to its widest child (WP-020d QA BUG-02).
- Everything else (custom fields, time range, sort, page size, report filter builder) goes in
  `FiltersDrawer`; the button counts what is set there. Filters apply as they change.

### Record page

```
RecordHeader  ◧ INC-12  Subject …………………  [status] [priority]   requester · Created …   👥 ☆
ActionBar     [Resolve] [Take] [Assign] [Start work]                          [More actions ▾]
AlertStrip    ⚠ 2 alerts · View
Tabs (main)                                              │ PropertiesPanel (320 px, sticky)
                                                         │ ▾ Properties  ▾ SLA  ▾ Assignment …
```

- `RecordPage` puts the tabs and the panel side by side from 992 px (`lg`); below it the panel
  folds into one "Properties" section above the tabs, open by default. RTL mirrors the page.
- The panel stays on every tab. Sections fold; keep their keys stable, other lanes fill them
  (lane A's SLA card goes into `sla`).

### Analytics and settings

- Reports and dashboards use `PageHeader` (with a back link on a single report or dashboard) and
  `FilterBar`. A dashboard shown on Home uses `PageHeader level={2}`: Home owns the h1.
- `KpiTile` is a number on a page: label, a 28 px value, an optional hint; a tile with `onClick`
  is a link to the list behind the number.
- Administration is one `PageHeader` (h1) with tabs; each admin section opens with
  `PageHeader level={2}` (title, count, actions, description).

### Settings page (template E, D-147)

Every setup page has the same shape: the setup menu on the start side (`AdminLayout`), the page
header, its settings in grouped cards, and one save bar. How to move a page onto it:

1. **Header.** `AdminLayout` gives the page its `SettingsPageHeader` (title and description from
   the setup map). A page with actions of its own passes them as the header's `primaryAction` and
   `actions` (at most four, one primary), never as buttons inside a card.
2. **Cards.** Group the settings in `SettingsCard`s (`@supportx/ui`): a title, one line of help said
   once for the group, and the fields with their labels above them. No save, reset or apply button
   inside a card.
3. **One save bar.** Keep the page's edits in `useSettingsDraft(saved)`: every card reads `draft`
   and calls `set({ field: value })`. Render one `StickySaveBar` at the end of the page with
   `changes`, `onDiscard={discard}` and `onSave`, which sends `changed` only, with If-Match on the
   version shown. The bar appears only while something differs from what is saved, asks before
   the tab closes, and its Save is a `WriteButton` (a read-only licence disables it with the
   reason). A page built on an antd `Form` can count its changes from `Form.useWatch([], form)`
   against the saved values instead of the hook (knowledge settings does this).
4. **Switches (the coordinator, 2026-11-09).** A page with any form field puts everything on it in
   the one save bar, switches included: a switch changes the draft, not the server. Instant apply
   on change is only for pages made of switches alone, and those keep their confirmation for a
   risky change (switching a feature off says what happens to existing results). A page never
   mixes the two. Where a confirmation guarded a switch, ask it on Save when the draft contains
   that change.
5. **Lists on settings pages** (statuses, reasons, types) stay lists with their own add, edit and
   delete in a drawer or dialog (`EditDrawer`, `RowActions`): they are records, not draft fields,
   and are not counted by the bar.
6. **Checks.** A test that changing a field shows the bar with its count, Discard returns to what
   is saved, Save sends only the changed fields with If-Match, and nothing in a card is a button.
   Add the page to the visual matrix (`ADMIN_SECTIONS` in `visual-matrix.spec.ts`).

Lane C owns the template and its own pages (knowledge, AI, branding, instance, files, licence);
lane A moves incidents, requests, portal, automation and SLA; lane B people, roles, organisation
(sites, departments, structure), security, mail and integrations, and the audit settings and
archives inside WP-064 (which reworks that page anyway). The coordinator, 2026-11-09.

## Actions (`ActionBar`, updates REQ-WI-010)

- Give every action a `rank` (lower is more useful) and mark everyday ones `primary`.
- Buttons: the allowed primary actions with the best ranks, at most `max` (4), shown in the
  record's fixed order. The best-ranked one is the primary button.
- "More actions" lists **every** action in one fixed order. Unavailable ones are disabled and say
  why (`whyNot`, a label, never a code). Destructive ones (`danger`) come last after a divider;
  give them `confirm` (a question, plus `confirmOk` / `confirmCancel` wording that never says
  just "Cancel" for a cancel action).
- With a read-only licence the bar disables every action with the read-only reason by itself.
- Test ids: a button is `testId`, its menu entry `${testId}-menu`, the menu button
  `${bar}-more`. Console tests use `src/test/actions.ts` (`clickAction`, `actionItem`), e2e the
  helpers in `e2e/tests/helpers.ts`; they work whether an action is a button or in the menu.

## Alerts

`AlertStrip` shows one alert as a strip. Two or more collapse into "N alerts · View", which
expands in place, so nothing below jumps when an alert arrives (REQ-WI-012).

## Navigation and preferences

The side menu with labels (208 px) is the default; icons only (64 px) is a per-user preference.
After go-live, a changed default never overwrites a preference a user has stored (D-124): only
users without a stored choice get the new default. The one-time move in migration 0051 was
approved for pre-pilot data only.

## Checks

- Every screen works in Arabic and Urdu (RTL) and at 390 px with no sideways scroll.
- axe in light, dark and high contrast; Arabic contrast is measured directly, because axe skips it
  on Arabic text.
- Keep test ids when a control moves; change tests in the same PR when it moves into a menu or
  a drawer.
