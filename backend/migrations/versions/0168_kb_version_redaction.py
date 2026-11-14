"""Redacting a passage in a published knowledge version (ADR-052 S2, D-171 a; lane C), 0168.

Published and superseded versions never change (0036's `kb_versions_frozen`, REQ-KB-020 AC2).
A person's erasure is the one exception: words naming them, chosen by an admin in the mentions
report, become the reserved marker in the version's title, body or keywords too, or the passage
would survive in the article and its history. This adds the one way to do that:

- `kb_redaction_kept(old, new)`: true when `new` is `old` with one or more non-empty stretches
  replaced by the marker `erased_on_request`, and nothing else changed (lane B's #511 review,
  condition 2). Pure, so harmless to anyone who calls it.
- `kb_redact_version(mention, value, keywords)`: migrator-owned (`create_definer_function`),
  bound like 0164's `history_redact_field`. It takes the mention only, never a field or record:
  - a redacted mention with redactor and time, of an erasure that may still redact, record type
    `kb_article_version`, in the caller's tenant (`app.tenant_id`);
  - the field comes from the mention (`title`, `body_html` or `keywords`);
  - the new value must pass `kb_redaction_kept` (keywords: same length, each item unchanged or
    passing it);
  - false and nothing written when nothing would change (idempotent).
  It marks the row with the transaction-local `supportx.kb_redaction` setting, updates the one
  field, and clears the setting again on every way out (lane B).
- The freeze lets a change through only when **both** hold: it runs as `kb_redact_version`'s
  owner, the migrator (so inside a definer function) **and** `supportx.kb_redaction` names this very row (the coordinator). The
  app role can set the setting but is never the migrator; another migrator-owned function never
  sets it. Language, number, article and status stay frozen even then.

The service writes the history (field named only, reason `erasure_redaction`), bumps the
version and raises the ordinary saved event in the same transaction. Search follows by itself
(`search_vector` is a computed column). The downgrade restores 0036's freeze exactly.

Revision ID: 0168
Revises: 0167
Created: 2026-11-14
"""

from collections.abc import Sequence

from alembic import op

from migrations.helpers import create_definer_function, drop_definer_function

revision: str = "0168"
down_revision: str | None = "0167"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MARKER = "erased_on_request"  # identity_access's ERASED_ON_REQUEST (the D2a marker)
FLAG = "supportx.kb_redaction"
# The tenant, from the transaction's setting: no parameter can name another one.
_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
# The erasure states in which a mention may be redacted (domain/erasure.py, "redact"); fixed
# here, as a merged migration never changes with the code.
_REDACTABLE = "'requested', 'approved'"

_FROZEN_CHECK = """
    OLD.status IN ('published', 'superseded') AND (
        NEW.title IS DISTINCT FROM OLD.title
        OR NEW.body_html IS DISTINCT FROM OLD.body_html
        OR NEW.keywords IS DISTINCT FROM OLD.keywords
        OR NEW.language IS DISTINCT FROM OLD.language
        OR NEW.number IS DISTINCT FROM OLD.number
        OR NEW.article_id IS DISTINCT FROM OLD.article_id
        OR (OLD.status = 'superseded' AND NEW.status IS DISTINCT FROM OLD.status)
    )"""

# 0036's freeze, word for word (the downgrade puts it back).
_FROZEN_0036 = f"""
CREATE OR REPLACE FUNCTION kb_versions_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF {_FROZEN_CHECK} THEN
        RAISE EXCEPTION 'a published knowledge version cannot change' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;
"""

_FROZEN_0168 = f"""
CREATE OR REPLACE FUNCTION kb_versions_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF {_FROZEN_CHECK} THEN
        -- The one exception (ADR-052): kb_redact_version, as the migrator, for this row only,
        -- and only its title, body or keywords.
        IF current_user = (
               SELECT pg_get_userbyid(p.proowner) FROM pg_proc p
                JOIN pg_namespace ns ON ns.oid = p.pronamespace
               WHERE p.proname = 'kb_redact_version' AND ns.nspname = 'public'
           )
           AND current_setting('{FLAG}', true) = NEW.id::text
           AND NEW.language IS NOT DISTINCT FROM OLD.language
           AND NEW.number IS NOT DISTINCT FROM OLD.number
           AND NEW.article_id IS NOT DISTINCT FROM OLD.article_id
           AND NEW.status IS NOT DISTINCT FROM OLD.status THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'a published knowledge version cannot change' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;
"""  # noqa: S608 - fixed names, no input

_KEPT = f"""
CREATE FUNCTION kb_redaction_kept(p_old text, p_new text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    parts text[];
    n integer;
    pos integer;
    found integer;
    i integer;
BEGIN
    IF p_old IS NULL OR p_new IS NULL OR p_new = p_old THEN
        RETURN false;
    END IF;
    parts := string_to_array(p_new, '{MARKER}');
    n := cardinality(parts);
    IF n < 2 THEN
        RETURN false;  -- no marker: not a redaction
    END IF;
    -- The first part is the old text's start; each marker stands for a non-empty stretch.
    IF left(p_old, length(parts[1])) <> parts[1] THEN
        RETURN false;
    END IF;
    pos := length(parts[1]);  -- characters of the old text accounted for so far
    FOR i IN 2 .. n - 1 LOOP
        found := position(parts[i] IN substr(p_old, pos + 2));
        IF found = 0 THEN
            RETURN false;
        END IF;
        pos := pos + 1 + found - 1 + length(parts[i]);
    END LOOP;
    -- The last part is the old text's end, after at least one replaced character.
    IF right(p_old, length(parts[n])) <> parts[n] OR length(p_old) - length(parts[n]) <= pos THEN
        RETURN false;
    END IF;
    RETURN true;
END $$;
"""

_REDACT = f"""
DECLARE
    t uuid := {_TENANT};
    m record;
    v record;
    i integer;
    old_text text;
BEGIN
    IF t IS NULL THEN
        RAISE EXCEPTION 'kb_redact_version needs app.tenant_id';
    END IF;
    SELECT x.record_id, x.field INTO m
      FROM person_erasure_mentions x
      JOIN person_erasures e ON e.tenant_id = x.tenant_id AND e.id = x.erasure_id
     WHERE x.tenant_id = t AND x.id = p_mention AND x.state = 'redacted'
       AND x.redacted_at IS NOT NULL AND x.redacted_by IS NOT NULL
       AND x.record_type = 'kb_article_version'
       AND x.field IN ('title', 'body_html', 'keywords')
       AND e.state IN ({_REDACTABLE});
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    SELECT id, title, body_html, keywords INTO v
      FROM kb_article_versions
     WHERE tenant_id = t AND id = m.record_id
       FOR UPDATE;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    IF m.field = 'keywords' THEN
        IF p_keywords IS NULL OR cardinality(p_keywords) <> cardinality(v.keywords) THEN
            RAISE EXCEPTION 'keywords: one value per keyword';
        END IF;
        IF p_keywords = v.keywords THEN
            RETURN false;
        END IF;
        FOR i IN 1 .. cardinality(v.keywords) LOOP
            IF p_keywords[i] IS DISTINCT FROM v.keywords[i]
               AND NOT kb_redaction_kept(v.keywords[i], p_keywords[i]) THEN
                RAISE EXCEPTION 'a keyword is not its old text with the marker in place';
            END IF;
        END LOOP;
    ELSE
        old_text := CASE m.field WHEN 'title' THEN v.title ELSE v.body_html END;
        IF p_value IS NOT DISTINCT FROM old_text THEN
            RETURN false;
        END IF;
        IF NOT kb_redaction_kept(old_text, p_value) THEN
            RAISE EXCEPTION 'the value is not the old text with the marker in place';
        END IF;
    END IF;
    PERFORM set_config('{FLAG}', v.id::text, true);
    BEGIN
        UPDATE kb_article_versions
           SET title = CASE WHEN m.field = 'title' THEN p_value ELSE title END,
               body_html = CASE WHEN m.field = 'body_html' THEN p_value ELSE body_html END,
               keywords = CASE WHEN m.field = 'keywords' THEN p_keywords ELSE keywords END
         WHERE tenant_id = t AND id = v.id;
    EXCEPTION WHEN OTHERS THEN
        PERFORM set_config('{FLAG}', '', true);
        RAISE;
    END;
    PERFORM set_config('{FLAG}', '', true);
    RETURN true;
END
"""  # noqa: S608 - fixed names, no input


def upgrade() -> None:
    """The marker check, the redaction function, and the freeze's one exception."""
    op.execute(_KEPT)
    create_definer_function(
        "kb_redact_version",
        "p_mention uuid, p_value text, p_keywords varchar[]",
        "boolean",
        _REDACT,
        language="plpgsql",
        volatility="VOLATILE",
    )
    op.execute(_FROZEN_0168)


def downgrade() -> None:
    """0036's freeze back, the functions gone (redacted text stays redacted)."""
    op.execute(_FROZEN_0036)
    drop_definer_function("kb_redact_version(uuid, text, varchar[])")
    op.execute("DROP FUNCTION kb_redaction_kept(text, text)")
