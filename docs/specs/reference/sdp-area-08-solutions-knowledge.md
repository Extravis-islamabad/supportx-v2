# Area 8: Solutions / Knowledge Base

## Navigation path

- Main left rail > Solutions (`/ui/solutions`); a solution is at `/ui/solutions/<id>/details`; add form at `/ui/solutions/add`.
- Setup > Customization > Solution Management > Configuration (`AdminDetails.cc?forwardTo=solutionconfiguration`).
- Requests: a request's Resolution tab, with the Search Solutions and Save and Add To Solutions options.
- Problems: a problem's Solution tab > Resolution.
- New Request form: the Suggested Solutions right panel.

## Screens and what they do

**Solutions list.**
- Left: a TOPIC tree with New, Expand/Collapse and a trashed-topics icon.
- Right: a views dropdown, a list/detail toggle, and a column chooser.
- Columns: Solutions, Shared to, Publish. Each row has a gear and an open-in-new-tab icon.
- Toolbar: New Solution, Share, Approve Actions (Approve, Reject), "..." (Move, Delete).
- Views: All Active Solutions, Approved Solutions, Approval Pending Solutions, Unapproved Solutions, Due for periodic review today, Due for periodic review in 15 (days), Expired Solutions, Trashed Solutions. The views dropdown is searchable.
- Existing data: topics Compliance and Security, General, Hardware (Desktop Hardware, Printers, Routers, Switches), Network (Internet), Phone (Mobile), Softwares (ServiceDesk Plus with sub-topics). Five sample solutions, SOL-1 to SOL-5. SOL-1 and SOL-4 are published; the rest are not.

**Topic management.**
- The New Topic dialog takes a name and a **mandatory icon** (pick from 16 or import an image). There is no parent field there.
- Subtopics come from the topic's context menu (right-click or gear): New (subtopic), Edit, Share, Topic Owner, Delete.
- The Share Topic dialog has Technician Groups* (default All Technicians) and warns it may overwrite the sharing already set on the solutions inside. Cancelled.

**New Solution form.** Offers a template picker (Android Template, General Solution Template). Fields are in the table below.

**Solution detail page.**
- Header: ID, title, status chip, Topic. Toolbar: Edit, Delete, Forward, Print, Actions.
- Body: content, a Like and a Dislike button with counts, and tabs Comments, Keywords, Associations, History.
- Right panel: Solution ID, Status, Template, Created By, Last Updated By, Review Date, Expiry Date, Views, Attachments, Shared to, Published to, and association counters (Referred in Problems, Linked Solutions, Referred in Requests).

## Fields

| Field | Type | Required | Options/values | Notes |
|---|---|---|---|---|
| Template | select | no | Android Template, General Solution Template | Pre-fills the form |
| Title | text | yes | | |
| Content | rich text | yes | | A first Add can fail with a content error if the editor text was not registered; typing one more character fixes it |
| Topic | searchable tree | yes | existing topics | |
| Review Date | date-time | no | | Must be in the future; today is rejected |
| Expiry Date | date-time | no | | |
| Keywords | text | shown as required | comma-separated | Used by search and by Suggested Solutions |
| Internal Comments | text | no | | |
| Attachments | file | no | | |
| Share to: Technician Groups | multi-select | yes | default All Technicians | |
| Publish in Self-Service Portal | checkbox | no | | Reveals User Groups* |
| User Groups | multi-select | yes when publishing | default All Users | No other requester groups exist here |
| Comment: Show this comment to requester | checkbox | no | | On each comment |
| Reset Likes and Dislikes | checkbox | no | | In the Approve dialog |

Topic fields: Topic Name* and Topic Icon*.

## Actions and menus

- **Create buttons:** Add, Add And Approve, Cancel. With "Publish in Self-Service Portal" ticked, plain Add disappears and only Add And Approve remains, so publishing always goes through approval.
- **Edit buttons:** Save, Save and Approve, Save as Draft, Cancel. With Publish ticked, only Save and Approve and Save as Draft remain. Save and Approve asks "Do you want to reset Likes and Dislikes?" (Yes/No).
- **Detail Actions menu:** Edit, Forward, Share, Publish, Submit for Approval, Approve, Reject, Delete. The set changes with state; for example, Approve was shown when Unapproved, and Publish was listed on an approved solution.
- **Share dialog (solution):** Technician Groups* (multi-select, default All Technicians), with Share/Cancel. This controls which technician groups see the solution.
- **Approve:** opens an Approvals dialog with Approve/Reject, Internal Comments and a "Reset Likes and Dislikes" checkbox (ticked by default).
- **List toolbar Share:** the same share action for the ticked solutions. Move, Delete and the Approve Actions (Approve/Reject) also work on ticked rows.
- **Request/problem Resolution tab:** Search Solutions, "Use Resolution Template", an editor, Save, Save and Add To Solutions, Cancel. Requests add a Request Status select and an Add Worklog checkbox.

## Configuration options

Setup > Customization > Solution Management > Configuration (viewed, not saved):
- Solution ID Prefix* (SOL) and Starting Solution ID* (8).
- "Allow Solution Approver to approve their own solutions" (on).
- "Show only approved solutions in Suggested Solutions and Resolution for technicians" (off).
- "Do not show Suggested Solutions on the New or Edit Request page" (off).
- "Do not allow Requesters to add or edit comments for the solution" (off).
- "Do not show the Solutions module to Requesters" (off).
- "Enable solution versioning" (off).

Setup > General Settings > Requester Portal has no solution-specific option. Solution visibility to requesters comes from the per-solution Publish and User Groups settings plus the two checkboxes above.

## Automation / triggers / rules in this area

- Approval is manual: Submit for Approval, then an approver clicks Approve or Reject. The "approve their own solutions" setting lets the author approve alone.
- Publishing happens only through the approve path.
- Review Date and Expiry Date drive three views: Due for periodic review today, Due for periodic review in 15, and Expired Solutions. No automated notifications could be tested without a mail server.
- I found no business rule, workflow or custom function that acts on solutions.
- Likes and dislikes can be reset on approval or on a Save and Approve.

## Behaviour observed in tests

1. **Create and status.** SOL-6 was created with Add and began as Unapproved, "Not Published". Like and Dislike counters appeared only after approval.
2. **Approval flow.** Submit for Approval failed with "Oops, outgoing mail server is not configured yet", so the review route cannot be tested here. Approve through the dialog set the status to Approved.
3. **Publishing.** Edit, then Save and Approve, gave "Published" to All users, with Review Date Oct 25 and Expiry Date Oct 31. Views climbed with each open (now 4).
4. **Likes and comments.** Like turned the button to "Liked" with count 1 immediately. A comment posted fine ("Comment added") and shows a lock icon, meaning it is internal, unless "Show this comment to requester" is ticked.
5. **Review views.** The "Due for periodic review in 15" view listed SOL-6, as expected from its Oct 25 review date.
6. **Request to solution.**
   - Request #42's Resolution tab: Search Solutions pre-fills the subject; "spooler" found SOL-6. Filters are Topic and Show Solutions (All, Approved, Approval Pending, Unapproved).
   - Copy to Resolution pastes "Title / Description" text into the editor.
   - Save and Add To Solutions opened a New Solution dialog, from which I created SOL-7 (Unapproved).
   - Afterwards the tab showed "Resolution Submitted" with "Referred Solutions [2]". Responded Time was stamped, and the request stayed Open.
7. **Problem to solution.** PB-5's Solution tab has Workaround and Resolution sections, each with Add. The Resolution editor has the same Search Solutions, template picker, Save and Save and Add To Solutions. Search on a problem is not pre-filled and lists all 7 solutions. The solution's Associations tab has a "Referred in Problems" table.
8. **Suggested Solutions panel** (New Incident form):
   - After the Subject field loses focus, a banner reads "Try the Suggested Solutions on the right panel" with a Hide Solutions link, and the panel lists matches with Copy to Resolution.
   - It matches words in title, content and keywords, not topic names. "printer spooler problem" returned SOL-6 and SOL-1. SOL-5 (topic "Printers") did not match.
   - Unapproved solutions are suggested by default (SOL-7 matched "request42 resolution") unless the approved-only setting is turned on.
   - I only typed the subject and did not submit the request.
9. **Sharing.** Default share is All Technicians. The Share dialog only offers technician groups, and this instance has none beyond the default. Per-site visibility is not offered on the solution; it comes through technician-group scope.

## Edition notes

Enterprise trial; everything above was available. No separate edition gates were visible in this area.

## Weak spots / confusing UX

- The Add button vanishes when Publish is ticked, with no explanation.
- The first Add can fail with a false content error until another keystroke registers the text.
- Keywords carry a required marker but behave as optional.
- Review Date rejects "today", so near-term reviews need a future time.
- The Approve path depends on mail. Without a mail server, Submit for Approval fails hard with no fallback.
- The Actions menu lists "Publish" even on a published solution.
- No page for a requester-side preview; there is no portal switch from the technician account.
- Topic creation forces an icon, which is awkward for bulk topics.
- Versioning and ratings are on and off, but there is no reporting visible in this module.

## Limits of this area

- The requester portal view was not seen. Viewing it needs a requester login or user creation, which is outside the rules, so I stopped there. What requesters see is inferred from the settings above: only Published solutions, only for the chosen User Groups, with comments marked "Show to requester", and the whole module can be hidden with the "Do not show the Solutions module" setting.
- The approval route could not be exercised because the mail server is not configured.
- Forward (email) was not used.

## Test records created

- Topic "ZZ-CLAUDE-TEST topic 1".
- SOL-6 "ZZ-CLAUDE-TEST solution 1" (Approved, Published to All users, review Oct 25, expiry Oct 31, 1 like, 1 internal comment).
- SOL-7 "ZZ-CLAUDE-TEST solution from request 42" (Unapproved, Not Published).
- Also from 7b: asset "Copy of ZZ-CLAUDE-TEST asset 1 - 22", plus ZZ-CLAUDE-TEST asset 1 now linked to PB-5 and CH-8.

=== END OF AREA 8 ===
