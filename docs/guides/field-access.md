# Field access by role

Some fields hold information that not everyone who works a record should see: a salary band, a
customer's account notes, the impact on a named person. Field access lets an administrator decide,
per role, how that role sees each such field. It needs the "Field Access by Role" part of the plan
(ADR-047).

## Where

**Admin › Roles**, open a role, then the **Field access** tab. The tab is there for saved roles,
built-in ones included. Changes on this tab save at once: there is no Save button.

## The modes

| Mode | What a person in the role gets |
|---|---|
| No rule | The field as usual. |
| Read only | The value, but they cannot change it. |
| Masked | The field is listed and reads "Masked"; the value never reaches their browser. |
| Hidden | The field reads "Not shown to you"; the value never reaches their browser. |

Masked and hidden fields are also read only.

## Several roles: the clearest wins

A person sees a field as clearly as their **clearest** role allows. If one of their roles has no
rule for the field, they see it in full, whatever their other roles say. To restrict a field for
someone, every role they hold must restrict it.

**Who sees this** (beside each field) shows, across every role, who sees the field in full, read
only, masked or not at all.

## What a rule covers

Wherever a restricted value could appear, it is withheld for that person: the record, lists and
exports, history, reports and dashboards, search (a value is never found by its words), live
updates, AI suggestions, and the automations they design (a rule, trigger, workflow or template
cannot name a field its author does not see in full). The requester portal is not affected.

The core fields (subject, description, status, priority, requester, group, assignee) cannot be
restricted: lists, notifications and SLAs need them.

## If the plan changes

If the plan no longer includes field access, every rule keeps applying. Rules can still be viewed
and removed, but not added or changed.

## Who may do this

Seeing the tab needs `roles.view`; changing rules needs `roles.manage`. A change asks you to
confirm your sign-in if you have not done so recently, and every change is recorded in the audit
log with the mode before and after.
