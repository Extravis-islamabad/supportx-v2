# ServiceDesk Plus reference notes

These files are capability notes taken from a ManageEngine ServiceDesk Plus trial (Enterprise
plan). They record what the product can do — screens, fields, value lists, actions, automation
and observed behaviour — so we can plan **parity of capabilities and outcomes** (architecture.md
§2, CLAUDE.md §2). They are input for specs and work packages, not a design to follow.

## Rules for using them

- **Describe capabilities in our own words.** When a note becomes a requirement, write what the
  user must be able to do, not how ServiceDesk Plus does it.
- **Never copy their UI, text or artwork.** No screen layouts, wording, help text, labels taken
  verbatim for our UI, icons, illustrations or colour schemes. SupportX screens are original and
  built on Ant Design 5. Value lists quoted here (statuses, priorities…) are examples of what an
  admin can configure, not seed data to copy.
- **No screenshots with personal data** may be committed. Prefer no screenshots at all; describe
  what was seen instead.
- **No real personal data.** Names in the notes are the trial's built-in demo users. The person
  who ran the trial is referred to as "the trial admin". Records created during exploration are
  named `ZZ-CLAUDE-TEST …` and exist only in the trial.
- The weak spots each note lists are where SupportX can do better; they are opinions from one
  exploration session, not verified product facts.

## Files

One file per area of the product, `sdp-area-<nn><part>-<topic>.md`. More areas are added the
same way.

| File | Area |
|---|---|
| [sdp-area-01-navigation.md](sdp-area-01-navigation.md) | Navigation and global UI |
| [sdp-area-02a-requests-list.md](sdp-area-02a-requests-list.md) | Requests: list views, filters, columns, bulk actions |
| [sdp-area-02b-new-request-form.md](sdp-area-02b-new-request-form.md) | Requests: new request form, templates, first test records |
| [sdp-area-02c-request-detail.md](sdp-area-02c-request-detail.md) | Requests: detail page actions (notes, worklog, tasks, assign, link, merge, close, cancel) |
| [sdp-area-03-service-catalog-portal.md](sdp-area-03-service-catalog-portal.md) | Service catalog and self-service portal |
| [sdp-area-04-problems.md](sdp-area-04-problems.md) | Problems: list, form, detail tabs, known errors, closure, templates |
| [sdp-area-05-changes.md](sdp-area-05-changes.md) | Changes: list, calendar, form, stages and workflow, scheduler, CAB, templates (5b: emergency/standard, links, freeze windows) |
| [sdp-area-06-releases-projects.md](sdp-area-06-releases-projects.md) | Releases and projects |
| [sdp-area-07-assets-cmdb-purchase.md](sdp-area-07-assets-cmdb-purchase.md) | Assets, CMDB, contracts and purchase |
