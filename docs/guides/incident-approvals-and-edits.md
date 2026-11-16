# Incident approvals and edits

## Asking for approval

On an incident, **Ask for approval** (the record's actions) names one or more people. With more
than one you choose how they decide:

| Rule | The approval is approved when | It is rejected when |
|---|---|---|
| Any one approver | the first one approves | the first one rejects |
| Every approver | all of them approve | any one rejects |
| A majority | more than half approve | a majority can no longer approve |

Each approver is asked in the app and by e-mail, with their own one-time link. Someone who
requested the incident, or for whom it was raised, cannot approve it. The **Approvals** tab shows
every approver and their decision as it happens. The incident's status does not change: its
approval status says how it went, and the technician is told if it is rejected.

## Editing a closed incident

A closed incident's fields are read only. People who hold **Edit closed incidents** (by default
the service desk managers; administrators hold every right) may still change them, saying why.
Each such change is in the record's history with the reason and in the audit log (which names
the fields, never their values). Notes and replies work as usual on a closed incident; reopening
it is a separate action.

**Settings › Incidents › Closing › Lock closed incidents** stops all such changes, for everyone,
administrators included. It saves at once and may ask you to confirm your sign-in.

## Reasons for changes

In the same settings, **Fields that need a reason to change** lists fields whose every change asks
"why". The reason is kept in the record's history.

## First-contact resolution

When an incident is resolved by the person who logged it, within the **first-contact window** and
without ever being handed to someone else, it is marked as resolved at first contact. The
technician can change the mark on the resolved incident; reports use their final word.

## Parent and child incidents

In an incident's **Links** tab, link another incident as a **child of this incident**. A child
has one parent, a parent is never itself a child, and a child has no children of its own. You
need to be able to edit both. Linking never shows anyone an incident they could not see before:
an incident you may not open shows as a hidden line.

When the parent is resolved, **Resolve the children too** lists its open children you may edit.
The chosen ones are resolved with the parent's resolution as a background job; each follows its
own rules, and its history names the parent.

## Merging duplicates

**Merge** an incident into another one. Before you confirm, you see:

- the children that move to the incident you keep;
- whether the duplicate's requester is added as a follower (only when both incidents are in the
  same department);
- how many people would newly see the duplicate: staff who can open the incident you keep but not
  the duplicate, and the requesters of the incident you keep. You confirm this explicitly.

The merged incident stays readable, marked as merged. Its notes and replies show on the incident
you keep, each with its own visibility: private notes never reach the portal.

**Undo merge** (by default the service desk managers; it asks you to confirm your sign-in) puts
everything back exactly. When that is no longer possible (the incident you kept has since been
closed, or a moved child was linked elsewhere) it is refused, and nothing changes.

## Converting between incidents and service requests

**Convert** an incident to a service request (choose the catalog item and answer its questions),
or a service request to an incident. A new record is created; the old one is marked converted
and stays readable, its history unchanged. The preview lists the custom fields that do not carry
over (the other type has no such field, or a field-access rule covers it); they stay on the old
record. Open approvals on the old record are withdrawn. Its old number still leads to the new
record, for anyone who may open it.
