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
