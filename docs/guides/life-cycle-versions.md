# Life cycle versions (incidents and service requests)

Admin › Incidents › Life cycle, and the bottom of Admin › Service requests. ADR-049; WP-046a S4a.

A life cycle is the set of status moves a record can make: from a status, an action (Start work,
Resolve, Cancel …) leads to another status. It comes in numbered **versions**.

## What a version holds, and what it does not

| Part of a move | Where it is set | Applies to |
|---|---|---|
| From status, action, to status | the version | records on that version only |
| The reason prompt (none, optional, required) | Statuses › reason prompts | every version at once |
| An extra right the move needs | the version | records on that version only |
| Fields that must be filled first | the version | records on that version only |
| Who may run it, when it is offered, its confirmation, what happens after | Automation › Transitions | **every version at once** |

The last row matters. Changing who may run a move, or when it is offered, changes every record's
buttons straight away, whatever version it runs on. A tighter rule protects every record at once.

## Versions

- **Published** versions never change. New records start on the one marked *New records start
  here* (the latest published) and keep it.
- **Draft**: at most one per life cycle. *Start a new version* copies the latest published version.
  Change its moves, then *Save draft*. A draft saves with its problems, each naming what to fix,
  for example "Awaiting requester has no way out". It publishes only when none are left.
- **Retired**: no longer offered to new records. The records already on it keep moving by it. The
  version new records start on cannot be retired.

## Publishing

Publishing changes what **new** records start on. **Existing records stay on the version they
started on and keep its moves.** Moving existing records to a newer version will be an
administrator action with a dry run (S4b). Until then, records move only by their own version.

Every change here needs the type's settings right, is audited as a settings change, and shows
on other admins' open screens straight away.
