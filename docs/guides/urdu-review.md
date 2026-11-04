# Urdu review: what to check and how

A native speaker reviews SupportX's Urdu before the pilot (product owner, 2026-11-04). Every
label has an Urdu translation, except one key kept in English on purpose (a test proves the
English fallback with it). Most of the older keys were translated in one batch (#190), so
wording, consistency and tone are what need a human eye.

## Switching the console to Urdu (shared stack)

1. Open the console on the shared stack: <http://localhost:5273>. The portal is on
   <http://localhost:5174>.
2. Sign in with the account the coordinator gives you. Use a reviewer account, never a
   colleague's.
3. Top right, open **Appearance** (the paint-bucket icon) and choose **اردو** under Language. The
   whole console switches to Urdu, right to left, and the choice is saved with your account, so
   it follows you to other browsers.
4. If اردو is missing from the list, the tenant does not offer Urdu: an admin switches it on in
   Admin › Instance settings › Languages offered.
5. To go back to English, choose **English** in the same place.

Note any wrong, unclear or inconsistent wording with the screen, the exact text and your
suggestion. A screenshot helps.

## Screens to check

| Area | Where | What to look at |
|---|---|---|
| Shell | Every page | Navigation menu, header, breadcrumbs, notices, the command palette (Ctrl K) |
| Home | Home | Welcome, plan and seats, dashboard titles |
| Incidents | Incidents list, an incident record | Columns, filters, statuses, priorities, the conversation (reply, note), history, SLA timers |
| New incident | Incidents › New | Field names, help texts, required-field messages |
| Knowledge | Knowledge, an article, the editor, the approval inbox | Article states, the editor's buttons, votes and feedback |
| Reports and dashboards | Reports, Dashboards | Report names, chart titles, time ranges |
| Announcements | Announcements | Severities, audiences, the publish window |
| My profile | Avatar › My profile | Display and region (theme, text size, formats, digits), notifications, signature |
| Admin | Admin (setup home) | Every setup page's name and explanation, the search, roles and permissions, people, instance settings |
| Errors | Anywhere | Messages after a refused or invalid action (e.g. save a form with a required field empty) |
| Portal | <http://localhost:5174> | Home, catalog, my requests |

## Label files

The Urdu text lives in `frontend/packages/labels/src/resources/<module>/ur.ts`, one file per
module, next to the English (`en.ts`) and Arabic (`ar.ts`) of the same keys:

| Module | Urdu labels | What it covers |
|---|---:|---|
| `shared` | 462 | Shell, navigation, actions, filters, appearance, setup home |
| `errors` | 559 | Every error message |
| `identity_access` | 730 | Sign-in, people, roles, permissions, profile and preferences |
| `work_items` | 809 | Incidents: fields, statuses, conversation, history, tasks |
| `knowledge` | 292 | Knowledge base |
| `analytics` | 462 | Reports and dashboards |
| `audit` | 511 | Audit log, event names |
| `automation` | 210 | Rules and triggers |
| `sla` | 179 | Service levels |
| `notifications` | 220 | Notifications and preferences |
| `integrations` | 304 | Mail, directories, connectors |
| `organization` | 151 | Sites, groups, branding, instance settings |
| `announcements` | 72 | Announcements |
| `licensing` | 72 | Plan, licence, features |
| `metadata` | 104 | Custom fields |
| `files` | 66 | Attachments |
| `ai` | (with WP-037) | AI settings and assistance |

Suggested corrections can come as notes or as a list of `key: new text`. A developer applies
them, and `make labels-sort` keeps each file in order.
