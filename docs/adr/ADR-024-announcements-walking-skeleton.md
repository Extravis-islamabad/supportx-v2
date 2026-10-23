# ADR-024: Announcements module as the walking skeleton; shared history, status machines, clock-driven visibility

- **Status:** Accepted
- **Date:** 2026-10-23
- **Source:** WP-012; architecture.md §6.1–§6.5, §7.4, §8, §10; ADR-022; ADR-023; D-032..D-034
- **Owner:** Haider (Product Owner)

## Context

WP-012 needed one business entity built through every layer, as the template later modules copy.
The product owner chose **announcements** (notices to everyone, to sites or to support groups,
optionally shown as banners and inside a publish window) and asked for a separate module, field
history, a status flow with reasons, a four-eyes option and a scheduled window that goes live on
every screen with no reload. Several of those pieces are platform concerns every module will need.

## Decision

1. **New module `announcements`** (architecture.md §6.1 lists the planned modules; this one is
   added by this ADR, D-032). Licensed with the `incident` feature (the service desk). Permissions
   `announcements.view` / `.manage` (scopes all, site, group, own) and `.publish` (all). A module
   now declares its built-in role defaults on the permission (`PermissionSpec.defaults`):
   technicians view all and manage their own; publishing and the four-eyes setting stay with
   administrators and custom roles. Own = owner or author; site / group = addressed to one of the
   user's sites / groups.
2. **Field history is a shared service** (`app/shared/history`, table `field_changes`, §7.4):
   every save writes one row per changed field with old and new value (JSON), actor, source
   (`ui` from the console/portal header `X-SupportX-Client`, `api` otherwise; `rule`, `workflow`,
   `ai_agent`, `system`, `import` reserved), request ID and an optional reason (≤ 500). The
   application may only insert and read (append-only grants). A stale `If-Match` 409 is explained
   from the same history (`changed_fields`, `changed_by`, `changed_at`), for announcements and the
   user profile. The tamper-evident (hash-chained) audit log of §7.4 is a later work package
   (D-034); this table is the record history, not that log.
3. **Statuses change only through named actions** (`app/shared/domain.StatusMachine`): a table
   status → {action → status} with a fixed action order. Disallowed moves are 409
   `invalid_transition`; the UI shows every action in that order, disabled with a reason code
   (`action_reason.*`) when not possible for this user now. Announcements: draft → published →
   draft (unpublish) / archived → draft (reopen); unpublish and archive take an optional reason.
4. **Visibility is computed, never stored.** A published announcement is `scheduled`, `live` or
   `ended` by its window at the moment of the request; drafts and archived ones are `hidden`.
   Nothing has to run at the window's start or end, so nothing can be late or missed.
   - **Live screens on the clock:** every list, record and feed response carries
     `next_change_in_seconds` (relative, so a wrong client clock does not matter); the client
     sets one timer and refetches then (`useRefetchAfter`). The feed's value also counts
     announcements addressed to the user that start later: only the moment leaks, never which
     announcement.
   - **Live screens on changes:** staff lists and records use the WP-011 channels (record with
     presence; lists per audience). Banners and the portal follow the tenant broadcast with an
     ID-free `announcements.feed_changed`, sent only when something published changed (a draft
     edit sends nothing), and refetch; the API filters by audience and window. A scheduler
     (Temporal) was not needed and is not built yet.
5. **Who sees what.** Staff read through `announcements.view` (scope-filtered SQL). Anyone signed
   in reads the feed and, by ID, an announcement that is live for them, as a reduced public view.
   Everything else is **404** (never 403), so a requester cannot learn that a draft exists; the
   record channel follows the same rule.
6. **Four-eyes** is a tenant setting (`announcement_settings.require_second_publisher`, off by
   default, versioned, history kept) applied as a WP-016 segregation-of-duties rule on publish.
7. **Housekeeping** (follow-ups of WP-007/WP-008): the outbox relay also deletes expired
   idempotency keys and consumer records older than `SUPPORTX_PROCESSED_EVENTS_RETENTION_DAYS`
   (30, minimum 7). Role-scoped RLS policies on those tables let the relay see only rows past the
   limits, so the database enforces the floor.

## Consequences

- Later modules copy the shape in `docs/architecture/module-template.md`: the history, status
  machine, action states, conflict explanation and clock-driven liveness come for free.
- `field_changes` grows with every save; partitioning and archiving follow with the audit log WP.
- Clients refetch at window boundaries: with many users that is one feed request per user per
  boundary (cheap, index-backed; measured p95 < 12 ms on 10,000 announcements).
- The body is plain text (D-033) until a rich-text editor library is chosen (before Knowledge).
