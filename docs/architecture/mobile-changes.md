# Changes on the mobile app: API audit and push format (WP-045d S4b; REQ-CHG-110)

This page is for the mobile team (WP-M6 push, and the technician app's change screens). It
lists the API a technician or approver needs to handle changes from the app, and proposes the
push payload and deep link for a pending approval (AC1). Nothing here sends a push: device
registration, the push channel adapter and the deep-link handling are WP-M6's
(docs/architecture/mobile.md on #236).

## Audit result

- **One API (P2).** The app calls the same `/api/v1/changes/...` routes as the console, so
  transitions, prompts, permissions, stage access and freeze or window checks are the same
  (AC2). There is no mobile-only route and none is needed.
- **Client header.** The app sends `X-SupportX-Client: mobile`. History then records the
  source as `ui`, like the console.
- **Fixed in this session:** approval decisions sent with `mobile` were recorded as made in
  the portal. They are now recorded as made in the app (`channel: "app"`), like the console
  (`approval_routes.py`, test `tests/db/test_change_mobile_api.py`).
- **Errors** are RFC 9457 with `code`, `message_key` and `params`; the app maps them through
  `@supportx/labels` like the console. A refused move answers 409 `stage_move_not_allowed` or
  `stage_move_refused` with the reasons in `params`.
- **Writes** need If-Match on the version read (409 with what changed) and an Idempotency-Key
  on creates. An offline queue must keep both.

## The routes the app needs

| Screen | Routes |
|---|---|
| Change lists | `GET /changes` (cursor pages, `view`, filters), `GET /changes/views`, `GET /changes/counters` (incl. `pending_my_approval`, `my_starting_today`), `GET /changes/search`, `GET /changes/lookup/{value}` |
| The record | `GET /changes/{id}`, `GET /changes/{id}/details`, `GET /changes/{id}/stages`, `GET /changes/{id}/schedule`, `GET /changes/{id}/plan`, `GET /changes/{id}/roles`, `GET /changes/{id}/sla`, `GET /changes/{id}/conflicts`, `GET /changes/{id}/history` |
| Stage moves | `POST /changes/{id}/moves` (If-Match; `to_status`, `reason_code` / `reason_text`, closure code where asked), `POST /changes/{id}/actions/{action}`, `POST /changes/{id}/take`, `POST /changes/{id}/assign` |
| Tasks | `GET/POST /changes/{id}/tasks`, `PATCH/DELETE /changes/{id}/tasks/{task_id}`, `GET /changes/my-tasks` |
| Notes and time | `GET/POST /changes/{id}/conversation`, `GET/POST /changes/{id}/worklogs` |
| Approvals | `GET /changes/my-approvals`, `GET /changes/my-approvals/decided`, `GET /changes/{id}/approvals`, `GET /changes/{id}/approvals/changes-since` (what changed since the approver last saw it, REQ-CHG-046), `POST /changes/{id}/approvals/{approval_id}/decision` (If-Match on the approval's version) |
| Notifications | `GET /notifications`, `POST /notifications/read`, `GET/PUT /notifications/preferences` |
| Live | `POST /realtime/connection-token`, `POST /realtime/subscription-token`; channels `t:{tenant}:wi:{id}` (the record) and the personal channel (`work_items.my_approvals_changed`, `work_items.my_tasks_changed`) |

The console-only parts (settings, templates, saved views, bulk, CAB pack print, downtimes
editing) are left out on purpose; the app may add them later through the same routes.

## Proposed push payload for a pending approval (AC1)

A push goes through FCM or APNs, which are third parties, so the payload carries **IDs and a
label key only**, never the change's subject, risk or requester (§8, rule 5c's spirit):

```json
{
  "kind": "approval_pending",
  "record_type": "change",
  "record_id": "<uuid>",
  "approval_id": "<uuid>",
  "display_id": "CHG-1042",
  "title_key": "notification_event.change.approval_requested",
  "link": "supportx://t/changes/<record_id>?approval=<approval_id>"
}
```

- The notification text is built on the device from `title_key` and `display_id` through
  `@supportx/labels`, in the person's language.
- `display_id` is the only record field. A tenant that wants even that hidden can drop it.
- The same shape serves service requests, problems and releases (`record_type`
  `service_request`, `problem`, `release`).

## Proposed deep link

`supportx://t/changes/{record_id}?approval={approval_id}` opens the change in the technician
app with its approval view on top. On open the app:

1. reads `GET /changes/my-approvals` and finds the approval. If it is gone (decided,
   withdrawn, or the person no longer approves), it shows the record with a "no longer
   waiting for you" notice, never an error;
2. shows `GET /changes/{id}/approvals/changes-since` for what changed;
3. decides with `POST /changes/{id}/approvals/{approval_id}/decision` and If-Match.

A person without `changes.view` who still approves (lane B's rule in S3) cannot open the
record. For them the link opens the app's approvals list, where the approval's number,
title and decision buttons are enough, as in the portal.

## Open for WP-M6

- Device registration and the push channel adapter (the notifications engine already sends
  per channel; push becomes one more channel).
- Whether the server or the app builds `link` (proposed: the server, so one place knows the
  routes).
- The app's route for changes (`t/changes/[id]`) next to `t/incident/[id]`.
