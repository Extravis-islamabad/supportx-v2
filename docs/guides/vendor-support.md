# Vendor support access

When Extravis needs to look inside your SupportX to help you, your tenant administrator grants a
named Extravis engineer time-limited access. You decide how long it lasts and what it allows, and
you can end it at any time. Everything the engineer does is in your audit log, as "Extravis
support" with the grant.

## Granting access

Admin › Security › Vendor support › **Grant access**:

- **The engineer:** their name and work e-mail. They prove who they are before the access starts.
- **Why:** a reason, and your support ticket's reference if you have one.
- **How long:** 24 hours by default, 72 hours at most. You can extend it while it runs.
- **What it allows:**
  - *View* (the default): they can read records and settings, and change nothing.
  - *View and change*: they can also make changes. Give a reason for the change too.

Granting and extending access ask you to confirm your sign-in. Every change to a grant is audited.

## What the engineer sees of people

- **Names are shown.** They see who raised a record and who works on it, so they can follow its
  history.
- **E-mail addresses and phone numbers are never shown**, whatever the grant says.
- **Searching for a person:** the engineer can find people by name only. Typing an e-mail address,
  or part of one, finds nobody.

### Known limitation

SupportX hides the fields that hold people's contact details: e-mail and phone.
**It does not find details that someone typed into free text**, such as an address or phone
number in a description, a comment or a reply. If a record's text contains them, the engineer
can read them. Keep this in mind when you grant access to records whose text is sensitive.

## What the engineer can never do

They can never become a tenant administrator, change sign-in or security settings, publish a
workflow, run automation tests, use AI features, or receive any notification or e-mail. Every file
they download is recorded in the audit log.

## Watching and ending access

Each grant's page shows its activity: everything the engineer's account did, from the audit log.
**End access** stops it at once: the engineer's next request is refused.
