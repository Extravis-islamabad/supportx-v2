"""Redacting a passage in a CI's saved snapshot (ADR-052 S1b, D-171 a; lane B), 0176.

`cmdb_ci_versions` keeps every saved state of a CI (0173). The app role may only add to it
(SELECT and INSERT), so an old snapshot naming a person being erased would survive their
erasure. The CMDB's mentions port lists each snapshot's name and description as their own
record type, `ci_version` (lane C's 0176 review, as 0168 does for KB versions). This adds the one
way to change a snapshot:

- `cmdb_redact_version(p_mention, p_value)`: migrator-owned (`create_definer_function`), bound
  like 0164's `history_redact_field` and 0168's `kb_redact_version`. It takes the mention, never
  a record or a field:
  - a redacted mention with redactor and time, of an erasure that may still redact, record type
    `ci_version`, field `name` or `description`, in the caller's tenant (`app.tenant_id` only);
  - the new value must pass 0168's `kb_redaction_kept(old, new)`: the old text with non-empty
    stretches replaced by the marker `erased_on_request`, nothing else changed (a pure check of
    the text's shape, generic over any text);
  - it writes that one key of that one snapshot and nothing else; false and nothing written when
    the value is unchanged (idempotent).

Snapshots feed no fingerprint or hash: the CMDB's history is `field_changes` (the registry
blanks it) and these rows are not signed (WP-064 signs work items only). The downgrade drops the
function; no data step.

Revision ID: 0176
Revises: 0173 (its base while building; re-pointed onto main's head at its queue turn)
Created: 2026-11-17
"""

from collections.abc import Sequence

from migrations.helpers import create_definer_function, drop_definer_function

revision: str = "0176"
down_revision: str | None = "0173"  # its base while building; re-pointed at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIGNATURE = "cmdb_redact_version(uuid, text)"
# The tenant, from the transaction's setting: no parameter can name another one.
_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
# The erasure states in which a mention may be redacted (domain/erasure.py, "redact"); fixed
# here, as a merged migration never changes with the code (as 0164 and 0168).
_REDACTABLE = "'requested', 'approved'"

_REDACT = f"""
DECLARE
    t uuid := {_TENANT};
    m record;
    v record;
    old_text text;
BEGIN
    IF t IS NULL THEN
        RAISE EXCEPTION 'cmdb_redact_version needs app.tenant_id';
    END IF;
    SELECT x.record_id, x.field INTO m
      FROM person_erasure_mentions x
      JOIN person_erasures e ON e.tenant_id = x.tenant_id AND e.id = x.erasure_id
     WHERE x.tenant_id = t AND x.id = p_mention AND x.state = 'redacted'
       AND x.redacted_at IS NOT NULL AND x.redacted_by IS NOT NULL
       AND x.record_type = 'ci_version'
       AND x.field IN ('name', 'description')
       AND e.state IN ({_REDACTABLE});
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    SELECT id, snapshot INTO v
      FROM cmdb_ci_versions
     WHERE tenant_id = t AND id = m.record_id
       FOR UPDATE;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    old_text := v.snapshot ->> m.field;
    IF p_value IS NOT DISTINCT FROM old_text THEN
        RETURN false;
    END IF;
    IF NOT kb_redaction_kept(old_text, p_value) THEN
        RAISE EXCEPTION 'the value is not the old text with the marker in place';
    END IF;
    UPDATE cmdb_ci_versions
       SET snapshot = jsonb_set(snapshot, ARRAY[m.field], to_jsonb(p_value))
     WHERE tenant_id = t AND id = v.id;
    RETURN true;
END
"""  # noqa: S608 - fixed names; the value is checked, never spliced


def upgrade() -> None:
    """The one way a snapshot changes: a redaction bound to its mention."""
    create_definer_function(
        "cmdb_redact_version",
        "p_mention uuid, p_value text",
        "boolean",
        _REDACT,
        language="plpgsql",
        volatility="VOLATILE",
    )


def downgrade() -> None:
    """Drop the function; snapshots stay as they are (a redaction is never undone)."""
    drop_definer_function(SIGNATURE)
