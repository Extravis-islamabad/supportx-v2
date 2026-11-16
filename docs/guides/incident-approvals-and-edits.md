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
