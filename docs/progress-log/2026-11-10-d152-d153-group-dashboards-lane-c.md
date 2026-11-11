### 2026-11-10 — D-152 group dashboards and D-153 release manager rights (lane C)

- **Group dashboards (D-152, migration 0123):**
  - `dashboards.group_id`, with no cross-module key: on save, the group is checked through
    organization's public service (rule 5e).
  - The group's members see the dashboard. Its lead (`may_manage_group`) or
    `dashboards.manage_defaults` change it. Another group's lead gets 403 `group_not_led`.
  - A group dashboard is never also shared with everyone (`ck_dashboards_group_or_shared`).
  - When its group is deleted, it falls back to its owner's private dashboards and shows as
    "group removed" to `dashboards.manage_defaults`.
  - The downgrade refuses while group dashboards exist (rule 5h). Its test stops at 0121, above
    0122, so WP-064's lifecycle refusal does not apply.
- **Console:** the picker has a My groups tab and shows the group's name; a lead can make a
  dashboard for their group.
- **Release manager (D-153):** holds every release permission at "all" except delete, and signs
  off releases. Stage segregation still stops them on a release they requested or own (test).
- **Built-in roles screen (D-153):** each role says what it is for and what it reaches. Built-in
  roles are not deleted; Copy and customise makes an editable copy.
- **Tests:**
  - test_dashboard_groups_migration 1, test_dashboards_api 12 and test_release_approvals_api 8
    pass;
  - console dashboards and admin 292 pass (5 failed once while load was 41 and passed on rerun);
  - labels 65 pass;
  - ruff, mypy and tsc are clean.
