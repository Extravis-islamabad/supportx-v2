# Notifications: the one notification engine

WP-023 (D-106). Every module that wants people told about its records registers through one
port; the `notifications` module decides who hears what, on which channel, in which language,
and records every message. Modules never send mail or in-app messages themselves
(`tests/test_notification_senders.py`).

## Registering a record type

```python
from app.shared.notifications.ports import (
    EventDefault, NotificationCategory, NotificationEvent, RecordAccess, RecordContext,
    register_record_source,
)

class KnowledgeNotifications:            # a RecordSource
    record_type = "kb_article"
    channel_kind = "kb"                  # its realtime record channel kind
    events = (
        NotificationEvent("kb_article.approved", NotificationCategory.STATUS,
                          EventDefault(enabled=True, recipients=("author",))),
    )
    recipient_kinds = ("author", "approvers", "followers")
    variables = (Variable("record.title", "notification_variable.record.title"), ...)
    conditions = ("category",)
    event_types = ("knowledge.article.approved",)

    def events_for(self, envelope): ...           # domain event -> notification event codes
    async def context(self, session, code, envelope) -> RecordContext | None: ...
    async def access(self, session, user_id, record_id) -> RecordAccess: ...

register_record_source(KnowledgeNotifications())  # at import, so the worker has it too
```

- `context` returns the record now: variables in two cuts (`variables` for full access,
  `public_variables` for people who may see only the public side), the people relative to it
  (`relatives`), values rules may test (`conditions`) and whether it is `urgent`.
- `access` uses the module's own visibility rules: FULL, PUBLIC (requesters) or NONE.
- An event with `public=False` (a private note) reaches only people with FULL access.
- Labels: `notification_event.<code>`, `notification_recipient.<kind>`,
  `notification_variable.<name>` and the default templates
  `notification_template.<code>.{in_app,subject,body}` in en, ar and ur (Jinja2 syntax,
  rendered in a sandbox).

Incidents are the first source: `work_items/service/notifications.py`.

## What the engine does with a committed event

1. The tenant's rule for the event, or its shipped default (no set-up step); its conditions.
2. Recipients resolved now (group members of today), de-duplicated, without the person who made
   the change unless the rule says so.
3. Per person: active with an address? may they see the record now, and how much? their
   preferences and do-not-disturb (required events are never held back).
4. In-app: an entry in their centre, pushed live on their personal channel (IDs only).
   E-mail: rendered in their language and zone, with the tenant's brand, queued through the one
   mail sender in the same transaction. With no outgoing mail, it waits (rendered) and admins
   see a banner; the `notifications__mail_waiting` schedule sends it once mail works.
5. A delivery row for every message, sent or not, with the reason (`no_access`, `preference`,
   `do_not_disturb`, `no_address`, `mail_refused`); e-mail rows show the mail sender's own
   state (sent, failed with its reason).

## API

| Route | Who |
|---|---|
| `GET /notifications`, `POST /notifications/read` | everyone, their own entries |
| `GET/PUT /notifications/preferences` | everyone, their own (If-Match) |
| `GET /notifications/rules`, `PUT/DELETE /notifications/rules/{event_code}` | `notifications.manage` (If-Match, audited) |
| `GET /notifications/status` | `notifications.manage` |
| `GET /notifications/deliveries?record_type=&record_id=` | people who may see the record in full |

Realtime: `notifications.created`, `notifications.read`, `notifications.preferences_changed`
(personal channel), `notifications.delivery_recorded` (record channel),
`notifications.rules_changed` (tenant broadcast).
