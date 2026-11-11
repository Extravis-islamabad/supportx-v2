# Releases: a guide for admins and release managers

Releases move through **stages**: submission, planning, build, testing, acceptance testing,
deployment, training, review and closure. Each stage has its own statuses, and a release can only
make the moves listed from its current status. The design is in ADR-041. The requirements are in
file 06 of the parity specs.

## Creating a release

- Choose a **template** first. The template decides which stages the release goes through:
  - the **standard** template takes every stage;
  - the **emergency** template skips planning and training, and shows an *Emergency* badge in
    lists.

  There is no separate workflow choice.
- Only the title is required. A new release starts in *Submission*.

## Moving a release on

- The **rail** at the top of a release shows each stage of its path:
  - done, current, skipped, or not yet;
  - how many times it was entered, since going back keeps the earlier rounds.
- The buttons under the rail are the moves you may make now. A disabled move says why: no
  permission, the stage's access rules, approvals still pending, or sub-releases not yet tested.
- A move asks only for what it needs:
  - a reason, when the move requires one;
  - any fields the template requires before leaving the stage;
  - the closure code, when the release closes.
- Reaching a stage's last status, for example *Completed* in build, moves the release on to the
  next stage straight away.

## Templates (Admin › Releases › Templates)

Per stage and per field, a template can:
- hide a field;
- make it required before leaving the stage;
- make it read-only while the release is in that stage.

A misspelt stage or field is refused when you save.

## Who may do what

- **Stage access** (Admin › Releases › Stages) limits who may edit a stage, and who may move a
  release out of it, by group, permission or release role. Rules to know:
  - an empty rule lets anyone who may edit the release act;
  - those who configure the service desk can always act, so no release gets stuck.
- **Roles** (the Roles tab): release manager, release engineer, development lead, QA lead,
  acceptance owner, reviewer and requester. Admins can add roles and say who may hold each one,
  by permission, group or person. The picker offers only people who may hold the role. Holding a
  role gives the person the release in their own views.

## Approvals

- Planning is approved by the release manager, and acceptance testing by the acceptance owner.
  Admins can change both, and add levels decided by **any one**, **every** or a **majority** of
  approvers. An exact split under majority is a rejection.
- People named on an approval decide it in the Approvals tab, or from the e-mailed link. No mail
  server is needed.
- The requester cannot approve their own release, unless an admin allows it in that stage's
  approval settings.
- A rejection always needs its reason. An approval needs a comment when the level asks for one.
- If nobody can be named (a role nobody holds, for example), the approval administrators get it,
  and the reason is shown.

## Changes in a release

The **Changes** tab lists the changes the release delivers:
- each with its number, title, stage and status, linked to the change;
- a change you may not see shows as *A change you can't see*.

To add one, search by number or title (needs *Edit releases*). A change can be in one open
release at a time: adding it to a second is refused, naming the release it is in. Once that
release is closed or canceled, the change may join another. **Take out** removes it. Both
records note the link in their history.

## The release calendar (Releases › Release calendar)

The releases you may see, by their deployment window and planned downtimes. It is the same
calendar as the change calendar:
- **views:** month, week, day, agenda and **timeline** (a row per release across the month);
- **layers:** freeze and maintenance windows;
- **Only mine:** the releases you hold.

Choosing a release opens a quick view, with a link to the release. **Move…** (or dragging) moves
a deployment window to another day at the same time of day.

**Show changes** draws changes on the same calendar, each type in its own colour with a legend
(it needs *View changes*). A change moves by its own rules: its implementation window, with its
re-approval warning. The change calendar has **Show releases** the same way.

**The release's scheduler:** *Open in the calendar* on a release's Schedule tab opens the
calendar on its deployment window, marks the release, and shows its own changes. Turn off
*Only its changes* to see every change.

## Freezes and conflicts

A release's **deployment window** and its **planned downtime** are checked against the freeze and
maintenance windows (Admin › Change and release windows), as a change's implementation is.
- **A blocking freeze** refuses the move, on every path, naming the freeze. Someone holding
  *Let a release go ahead in a freeze* (the release manager and administrators) can pass it with
  a reason: on the release's Schedule tab, or right away when a calendar move is refused. Only the
  freezes named are passed; a freeze added later still blocks. The reason is kept in the release's
  history and the audit log.
- **Outside every maintenance window** a release is warned, never refused (the change setting that
  blocks it applies to changes only).
- **Overlaps:** another change or release planned at the same time in the same group or site, or
  whose planned downtime names the same service or configuration item. They are named by number
  and type only; open them to see more if you may.
- **Booked twice:** the release manager or engineer is on another deployment at the same time.

The Schedule tab lists the conflicts as they are now and updates live. A warning can be
**acknowledged** with a reason: it stays listed, marked with who and why. If either side moves, the
conflict is shown again as new. A block is never acknowledged. Calendar chips show how many
conflicts each planned window has.

## Plan, schedule, downtime and sub-releases

- **Plan:**
  - the impact, rollout and backout plans and the review notes are separate sections;
  - two people can edit different sections at the same time.
- **Schedule:**
  - each stage's planned and actual dates; the actual dates are set as the release moves;
  - correcting an actual date needs a reason;
  - stages with work record an outcome, and a failed one needs its issues.
- **Downtime:** planned and actual windows, with the services and configuration items they
  affect.
- **Sub-releases:** a release can have one parent. The parent cannot enter deployment until every
  sub-release has passed testing.
