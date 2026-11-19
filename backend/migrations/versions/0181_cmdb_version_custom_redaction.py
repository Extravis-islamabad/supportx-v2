"""Redacting a passage in a CI snapshot's custom value (ADR-052 S1b, D-171 a; lane B), 0181.

0175 part 2 puts a CI's custom values into its saved snapshots (`cmdb_ci_versions.snapshot`
-> `custom`), so text a person typed into a custom field (text, long text, email, phone, link,
or a field removed since) survives in old versions. The CMDB's mentions port lists each such
value as a `ci_version` mention with field `custom.<key>`. 0176's `cmdb_redact_version` writes
only `name` and `description`, so this adds the one way to change a snapshot's custom value:

- `cmdb_redact_version_custom(p_mention, p_value)`: migrator-owned (`create_definer_function`),
  bound like 0176's `cmdb_redact_version`. It takes the mention, never a record, a field or a key:
  - a redacted mention with redactor and time, of an erasure that may still redact, record type
    `ci_version`, field `custom.<key>` with a non-empty key, in the caller's tenant
    (`app.tenant_id` only);
  - the snapshot's value under `custom` -> key must be a JSON string (typed text); a missing or
    non-text value refuses (an exception, as 0176 does for a missing old text);
  - the new value must pass 0168's `kb_redaction_kept(old, new)`: the old text with non-empty
    stretches replaced by the marker `erased_on_request`, nothing else changed;
  - it writes that one key of that one snapshot's `custom` and nothing else; false and nothing
    written when the value is unchanged (idempotent).

Person-type custom values (IDs) in snapshots are not touched: as for the owner in 0176, a
snapshot keeps the old ID and the person's own row is what the erasure anonymises. The downgrade
drops the function; no data step.

Revision ID: 0181
Revises: 0178 (main's head at its queue turn: 0180 → 0178 → 0181)
Created: 2026-11-18
"""

from collections.abc import Sequence

from migrations.helpers import create_definer_function, drop_definer_function

revision: str = "0181"
down_revision: str | None = "0178"  # main's head at its queue turn (0180 → 0178 → 0181)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIGNATURE = "cmdb_redact_version_custom(uuid, text)"
# The tenant, from the transaction's setting: no parameter can name another one.
_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
# The erasure states in which a mention may be redacted (domain/erasure.py, "redact"); fixed
# here, as a merged migration never changes with the code (as 0164, 0168 and 0176).
_REDACTABLE = "'requested', 'approved'"
# The mention field's prefix for a custom value (cmdb/domain/field_access.py CUSTOM).
_PREFIX = "custom."

_REDACT = f"""
DECLARE
    t uuid := {_TENANT};
    m record;
    v record;
    k text;
    held jsonb;
    old_text text;
BEGIN
    IF t IS NULL THEN
        RAISE EXCEPTION 'cmdb_redact_version_custom needs app.tenant_id';
    END IF;
    -- A redaction always has a value: NULL is refused here, before any lookup (lane C, #550).
    IF p_value IS NULL THEN
        RAISE EXCEPTION 'cmdb_redact_version_custom needs a value';
    END IF;
    SELECT x.record_id, x.field INTO m
      FROM person_erasure_mentions x
      JOIN person_erasures e ON e.tenant_id = x.tenant_id AND e.id = x.erasure_id
     WHERE x.tenant_id = t AND x.id = p_mention AND x.state = 'redacted'
       AND x.redacted_at IS NOT NULL AND x.redacted_by IS NOT NULL
       AND x.record_type = 'ci_version'
       AND left(x.field, {len(_PREFIX)}) = '{_PREFIX}'
       AND length(x.field) > {len(_PREFIX)}
       AND e.state IN ({_REDACTABLE});
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    k := substr(m.field, {len(_PREFIX) + 1});
    SELECT id, snapshot INTO v
      FROM cmdb_ci_versions
     WHERE tenant_id = t AND id = m.record_id
       FOR UPDATE;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    held := v.snapshot -> 'custom' -> k;
    -- Only typed text is a passage; a missing or non-text value leaves old_text NULL, which the
    -- check below refuses (never a silent false, as 0176).
    IF held IS NOT NULL AND jsonb_typeof(held) = 'string' THEN
        old_text := held #>> '{{}}';
    END IF;
    IF p_value IS NOT DISTINCT FROM old_text THEN
        RETURN false;
    END IF;
    -- Never NULL-tolerant: a missing old text, or a check that does not answer true, refuses
    -- (as 0176, lane C's #533 review).
    IF old_text IS NULL OR kb_redaction_kept(old_text, p_value) IS NOT TRUE THEN
        RAISE EXCEPTION 'the value is not the old text with the marker in place';
    END IF;
    UPDATE cmdb_ci_versions
       SET snapshot = jsonb_set(snapshot, ARRAY['custom', k], to_jsonb(p_value))
     WHERE tenant_id = t AND id = v.id;
    RETURN true;
END
"""  # noqa: S608 - fixed names; the key comes from the bound mention, the value is checked


def upgrade() -> None:
    """The one way a snapshot's custom value changes: a redaction bound to its mention."""
    create_definer_function(
        "cmdb_redact_version_custom",
        "p_mention uuid, p_value text",
        "boolean",
        _REDACT,
        language="plpgsql",
        volatility="VOLATILE",
    )


def downgrade() -> None:
    """Drop the function; snapshots stay as they are (a redaction is never undone)."""
    drop_definer_function(SIGNATURE)
