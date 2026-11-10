# Change approvals: advisory boards and segregation of duties (admin guide)

This guide covers who approves a change: advisory boards, how a change finds its board, and the
segregation-of-duties setting. The requirements are in file 05 of the parity specs
(REQ-CHG-039 to -042).

## Advisory boards (Admin › Changes › Advisory boards)

- Every organisation starts with two boards, both without members:
  - the **Change advisory board**, the default board, which reviews every change that no other
    board is mapped to. It can't be removed;
  - the **Emergency change board**, mapped to emergency changes.
- Add members before you use a board. A member is a person or a group (every member of the group
  approves). A board you create needs at least one member, and its members can't all be removed.
- A board decides by its **rule**:
  - *any member*: the first approval approves;
  - *all members*: everyone must approve;
  - *majority*: more than half must approve;
  - *majority, chair breaks ties*: as majority, with the chair deciding a tie. Until the chair's
    tie-break arrives, these boards decide by plain majority.
- **Optional** members are listed on the board but are not counted in the decision.

## Which board reviews a change

- A board's **mapping** names the changes it reviews: change types, risk levels, sites and
  templates. Leave a list empty to match anything. A board with an empty mapping reviews nothing
  by mapping.
- Boards are tried in their order. By default the first matching board reviews. Turn on
  **Every matching board reviews** (Admin › Changes › Settings) to send a change to every match.
- When nothing matches, the default board reviews. The approval says which board and why: *its
  mapping matched* or *default board*.
- To use boards, name **the mapped board** (or a specific board) as an approver of a stage's
  approval level (Admin › Changes › Stages).
- If the chosen board has no members yet, the approval administrators decide instead. The
  approval says *the advisory board has no members yet*.

## Segregation of duties

- The requester never approves their own change, unless the stage allows self-approval.
- By default, the change's **implementer** (the people assigned) and its **owner** (the
  technician) never approve it. Members of an implementing *group* still may.
- **Strict segregation** (Admin › Changes › Settings) also bars every member of an implementing
  group. We recommend it for regulated organisations (finance, health, government), where an
  auditor expects nobody on the implementing team to approve the change.
- Before a change is submitted for approval, the change shows who would approve it. It also
  shows who is left out and why, and that the approval administrators decide when nobody else
  can.
- A fallback is never silent:
  - the approval row shows its reason;
  - the change's history records it;
  - the audit log records *Approval went to the approval administrators*, with the level, the
    reason and the board.
- Changing the strict setting is audited as a change-settings change.
