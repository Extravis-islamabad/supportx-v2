# Label resources

Every text the UI shows comes from here (CLAUDE.md §5d). Each module keeps its labels in its own
folder, one file per language:

```
resources/<module>/en.ts   English, the reference (`as const`)
resources/<module>/ar.ts   Arabic, required for every key (D-006)
resources/<module>/ur.ts   Urdu, required for every new key (D-006)
resources/{en,ar,ur}.ts    join the modules into the one dictionary the app, i18next and
                           `make labels-json` (the backend's copy) use; nothing else goes there
```

Lanes adding labels in different modules never touch the same file, so label additions stop
conflicting between PRs.

## How to add a label

1. Find the module that owns the key's prefix in the table below (`incidents.*` → `work_items`).
   A new prefix goes with the module whose screens or enum use it; `shared` only for app-wide
   words (actions, appearance, shell); `errors` for every `errors.*` code.
2. Add the key to `<module>/en.ts`, `<module>/ar.ts` and `<module>/ur.ts`. Counted labels need
   the plural forms: English and Urdu `_one`/`_other`, Arabic all six (`_zero` … `_other`).
3. Run `make labels-json` (the backend's copy) and `pnpm --filter @supportx/labels test`.
   `modules.test.ts` fails when a key sits in two modules, sits in a different module in another
   language, lacks Arabic, or lacks Urdu (except the frozen list below).

A brand-new module folder also needs its three imports in `en.ts`, `ar.ts` and `ur.ts`, in the
spread and in the `…ByModule` map.

## Urdu still to translate

`ur-missing.json` lists the 370 older keys that had no Urdu when the files were split (they fall
back to English). The list only shrinks: translate a key, then delete its line, or the test fails.
They are translated before the pilot and checked by a native speaker.

## Modules and the prefixes they own

| Module          | Keys | Prefixes (examples)                                                                                                                                                                                                                              |
| --------------- | ---: | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| shared          |  384 | actions, antd, app, appearance, filter, filter_op, home, nav, palette, richtext, search, shell                                                                                                                                                   |
| errors          |  486 | errors                                                                                                                                                                                                                                           |
| analytics       |  458 | reports, report__, dashboards, dashboard__, measure, widget_*, age_bucket                                                                                                                                                                        |
| announcements   |   70 | announcements, announcement_*                                                                                                                                                                                                                    |
| audit           |  479 | audit, audit_*, event_type, actor_type, change_source, change_kind, history                                                                                                                                                                      |
| automation      |  209 | automation, automation__, rule__, trigger_*, loop_stop                                                                                                                                                                                           |
| files           |   64 | files, file_*                                                                                                                                                                                                                                    |
| identity_access |  621 | security, permission, permission_module, roles, role, people, people__, users, account, auth, session, sso__, mfa_mode, password_policy__, invitation__, sign_in_*, access, scope, profile, nav_layout, availability, presence                   |
| integrations    |  292 | mail, mail__, mailbox__, connector__, integrations, directories, directory__, domains, domain_*, secret_type, sync_scope, email_from                                                                                                             |
| knowledge       |   15 | kb_*, knowledge                                                                                                                                                                                                                                  |
| licensing       |   51 | licence, feature, edition, entitlement_*, limit                                                                                                                                                                                                  |
| metadata        |  104 | custom_fields, custom_field_*, pick_list, list                                                                                                                                                                                                   |
| notifications   |  180 | notifications, notification__, delivery__, event_delivery_*                                                                                                                                                                                      |
| organization    |  124 | organization, branding, weekday, desk, tenant_status                                                                                                                                                                                             |
| sla             |  140 | sla, sla_*                                                                                                                                                                                                                                       |
| work_items      |  733 | incidents, work_item__, conversation, templates, reply_templates, closure_code, task__, link__, worklog_type, followers, priority, urgency, impact, level, bulk__, categories, reason, reason_*, action_reason, access_settings, status_category |
