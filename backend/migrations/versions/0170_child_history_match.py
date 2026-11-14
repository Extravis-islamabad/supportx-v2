"""A task mention's parent history, matched more narrowly (ADR-052; lane C's #511 notes), 0170.

0167's `history_child_rows(mention)` finds the parent work item's `task*` history rows that name
the erased person. Two of its matches over-reach (they only ever blank more, never write):

- A phone was looked for in all of a value's digits joined, so two numbers next to each other
  could form a false match. Now each phone-like run of digits (the same shape as the Python
  matcher's, domain/mentions.py) is compared on its own: the same digits, or the same last 9
  when both have at least 9.
- A one-word display name was searched however short. Now the full first + last name is always
  searched, and a one-word display name only from 4 characters (counted as characters, so
  Arabic and Urdu by letter); the report flags a short name it skipped (the coordinator,
  2026-11-14). The address is unchanged.

The function is replaced (dropped and made again through the definer helper, in this one
transaction); its callers (`history_redact_child`, `history_redact_signed`) call it by name and
need no change. The downgrade puts 0167's body back. No data step.

Revision ID: 0170
Revises: 0167 (main's head while building; re-pointed at its queue turn)
Created: 2026-11-14
"""

import importlib
from collections.abc import Sequence

from migrations.helpers import create_definer_function, drop_definer_function

revision: str = "0170"
down_revision: str | None = "0167"  # main's head while building; re-pointed at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIGNATURE = "history_child_rows(uuid)"
_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_REDACTABLE = "'requested', 'approved'"  # domain/erasure.py, "redact"; fixed in a migration
SINGLE_NAME_MIN = 4  # domain/mentions.py SINGLE_NAME_MIN
# A phone-like run (domain/mentions.py `_PHONE_RUN`): digits with the usual separators.
_PHONE_RUN = r"\+?\(?\d[\d\s().\-]{4,}\d"
_DIGITS = "regexp_replace({}, '[^0-9]', '', 'g')"


def _phone(column: str) -> str:
    """A phone matches a run of the value's digits: equal, or the same last 9 when both >= 9."""
    mine = _DIGITS.format(f"coalesce({column}, '')")
    run = _DIGITS.format("r.m[1]")
    return f"""(length({mine}) >= 7 AND EXISTS (
            SELECT 1 FROM regexp_matches(s.raw, '{_PHONE_RUN}', 'g') AS r(m)
             WHERE {run} = {mine}
                OR (length({run}) >= 9 AND length({mine}) >= 9
                    AND right({run}, 9) = right({mine}, 9))))"""  # noqa: S608 - fixed names


_CHILD_ROWS = f"""
    SELECT f.id
      FROM person_erasure_mentions x
      JOIN person_erasures e ON e.tenant_id = x.tenant_id AND e.id = x.erasure_id
      JOIN users u ON u.tenant_id = x.tenant_id AND u.id = e.person_id
      JOIN work_item_tasks k ON k.tenant_id = x.tenant_id AND k.id = x.record_id
      JOIN field_changes f
        ON f.tenant_id = x.tenant_id AND f.record_type = 'work_item'
       AND f.record_id = k.work_item_id AND (f.field = 'task' OR f.field LIKE 'task.%')
     CROSS JOIN LATERAL (
         -- ' | ' between old and new: a phone run (which allows spaces) never spans the two.
         SELECT coalesce(f.old_value::text, '') || ' | ' || coalesce(f.new_value::text, '')
                    AS raw,
                lower(coalesce(f.old_value::text, '') || ' ' || coalesce(f.new_value::text, ''))
                    AS v,
                btrim(coalesce(u.first_name, '') || ' ' || coalesce(u.last_name, '')) AS full_name,
                btrim(coalesce(u.display_name, '')) AS shown
     ) s
     WHERE x.tenant_id = {_TENANT} AND x.id = p_mention AND x.state = 'redacted'
       AND x.redacted_at IS NOT NULL AND x.redacted_by IS NOT NULL
       AND e.state IN ({_REDACTABLE})
       AND x.record_type = 'work_item_task' AND x.field IN ('title', 'description')
       AND (f.old_value IS NOT NULL OR f.new_value IS NOT NULL)
       AND (
           -- The full first + last name, always (whatever its length).
           (coalesce(u.first_name, '') <> '' AND coalesce(u.last_name, '') <> ''
            AND strpos(s.v, lower(s.full_name)) > 0)
           -- The display name: several words always, one word from {SINGLE_NAME_MIN} characters.
        OR (s.shown <> ''
            AND (strpos(s.shown, ' ') > 0 OR char_length(s.shown) >= {SINGLE_NAME_MIN})
            AND strpos(s.v, lower(s.shown)) > 0)
        OR (coalesce(u.email, '') <> '' AND strpos(s.v, lower(u.email)) > 0)
        OR {_phone("u.phone")}
        OR {_phone("u.mobile")}
       )
"""  # noqa: S608 - fixed names, no input


def upgrade() -> None:
    """Replaces `history_child_rows` with the narrower match."""
    drop_definer_function(SIGNATURE)
    create_definer_function("history_child_rows", "p_mention uuid", "SETOF uuid", _CHILD_ROWS)


def downgrade() -> None:
    """Puts 0167's body back (read from that migration, never changed)."""
    previous = importlib.import_module("migrations.versions.0167_signed_history_redaction")
    drop_definer_function(SIGNATURE)
    create_definer_function(
        "history_child_rows",
        "p_mention uuid",
        "SETOF uuid",
        previous._CHILD_ROWS,  # noqa: SLF001 - the merged migration's own body
    )
