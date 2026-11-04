### 2026-11-04 — WP-042 sessions 2 and 3: roles screens, instance settings, preferences, announcement audiences (lane C)

**Session 2 (roles, REQ-ADM-015..019, 021)**

- Roles can be compared side by side and copied. The role editor lists a role's support groups,
  and a group's roles reach every member (`group_roles`, migration 0061). Both the escalation
  guard and the last-admin guard count roles held through groups. A group that still carries
  the last tenant admin cannot be disabled.
- New built-in roles: service desk manager, site admin, report viewer. Each module declares its
  own default grants.
- Configuration rights per area: `config.service_desk`, `config.organisation`,
  `config.announcements`, `config.reports`, each accepted alongside `settings.manage`. A test
  walks every route.
- Reviews: lane B approved group roles; lane A approved the role defaults and config rights.

**Session 3**

- Instance settings (`/admin/instance`; REQ-ADM-049, 050, 052), migration 0066:
  - Defaults for people and sites.
  - The base currency, which once set changes only after a confirmation.
  - The languages offered; English is always offered.
  - The tenant's time zone may be left unset (null). People with no time zone of their own or
    their site's then keep their browser's (lane B review: a UTC default would have moved every
    existing tenant's on-screen times).
  - A language the tenant switches off falls back to the tenant's default at sign-in.
- Personal preferences (REQ-ADM-058, 059, 062), migration 0067:
  - Five nullable columns on users: theme, text size (90 to 150 %), week start, date format,
    time format.
  - NULL means "not chosen". `/auth/me` applies the default at read time: the site's time zone,
    else the tenant's; the tenant's formats. A changed default therefore never overwrites anyone's
    own choice (Haider's rule).
  - The profile page has a "Display and region" card, and "Default" clears a choice.
  - The console applies the theme and text size from the session on every tab. A change on
    another device arrives through `users.changed`, which refreshes the session.
  - Someone who never chose a theme gets this browser's remembered theme copied to the server
    once.
  - The header's language list shows only the languages the tenant offers.
  - Lane B reviewed and approved aff4ed88 and daec216c.
- Announcement audiences (REQ-ADM-077), migration 0068: "requesters only" and "technicians
  only". A person whose only role is requester sees the first; everyone else sees the second.
  Neither audience names sites or groups.
- The role editor's groups section now says that a group filled by directory sync gives the
  role to everyone the sync adds (lane B's hint).
- Home dashboard (REQ-ADM-058): already per person in analytics (`set_home`). The preferences
  page does not duplicate it.

**Gaps and follow-ups (recorded, not done)**

- REQ-ADM-059 names a number format. Neither the tenant's settings nor a person's have one yet,
  and it needs a decision on the choices offered.
- REQ-ADM-062 AC2 (no cut-off text at 150 % on the record page) is not checked by e2e yet. Text
  size scales Ant Design's font sizes, control heights and menu and header heights.
- REQ-ADM-062 AC1 (high-contrast axe on the incident list and record) is covered by the existing
  theme contrast tests, not by a new e2e.
- nav_layout and form_density keep their non-null server defaults. Making them nullable would
  change their contract and is left for a later contract change.
