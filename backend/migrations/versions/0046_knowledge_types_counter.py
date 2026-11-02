"""Knowledge settings page: editable article types and the article counter (WP-033 3b, D-120).

- `kb_types` gets `version`, `updated_at` and `updated_by`: admins change types with If-Match
  (rule g). Expand only: defaults fill existing rows.
- Articles get their own named counter `KB_ARTICLE`, as incidents have `WI_INCIDENT`. Sessions 1-2
  counted by the display prefix ("KB"), so a renamed prefix would have restarted at 1. Each
  tenant's new counter starts at the highest number already handed out: the old prefix counter
  or the highest article number, whichever is larger. Existing articles keep their IDs.
- Self-approval is off by default for tenants that have no settings row yet (D-120 (4)); a
  tenant's stored choice is not changed.

Revision ID: 0046
Revises: 0041 (re-pointed onto the head of main only if the merge queue rejects it)
Created: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The counter key, spelled out in the SQL below: app.modules.knowledge.domain COUNTER_KEY.
# display_id_sequences, kb_articles and kb_settings have FORCE ROW LEVEL SECURITY: a data step
# sees rows only with app.tenant_id set, so it runs once per tenant (D-113; the migrator may read
# every tenant). The article number is the part after the last "-" of its display ID.
_START_COUNTER = """
DO $$
DECLARE t uuid; last bigint;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        SELECT GREATEST(
            COALESCE((
                SELECT s.last_value FROM display_id_sequences s
                WHERE s.tenant_id = t AND s.prefix = COALESCE(
                    (SELECT k.prefix FROM kb_settings k WHERE k.tenant_id = t), 'KB')
            ), 0),
            COALESCE((
                SELECT MAX(substring(a.display_id from '-([0-9]+)$')::bigint) FROM kb_articles a
                WHERE a.tenant_id = t
            ), 0)
        ) INTO last;
        IF last > 0 THEN
            INSERT INTO display_id_sequences (tenant_id, prefix, last_value)
            VALUES (t, 'KB_ARTICLE', last)
            ON CONFLICT (tenant_id, prefix)
            DO UPDATE SET last_value = GREATEST(display_id_sequences.last_value, EXCLUDED.last_value);
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""

# Back to counting by prefix: the prefix counter takes over the highest number either handed out,
# so a downgrade never hands out an ID twice.
_BACK_TO_PREFIX = """
DO $$
DECLARE t uuid; last bigint; old_prefix text;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        SELECT s.last_value INTO last FROM display_id_sequences s
        WHERE s.tenant_id = t AND s.prefix = 'KB_ARTICLE';
        IF last IS NOT NULL THEN
            old_prefix := COALESCE((SELECT k.prefix FROM kb_settings k WHERE k.tenant_id = t), 'KB');
            INSERT INTO display_id_sequences (tenant_id, prefix, last_value)
            VALUES (t, old_prefix, last)
            ON CONFLICT (tenant_id, prefix)
            DO UPDATE SET last_value = GREATEST(display_id_sequences.last_value, EXCLUDED.last_value);
            DELETE FROM display_id_sequences WHERE tenant_id = t AND prefix = 'KB_ARTICLE';
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def upgrade() -> None:
    op.add_column(
        "kb_types", sa.Column("version", sa.BigInteger(), server_default="1", nullable=False)
    )
    op.add_column(
        "kb_types",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column("kb_types", sa.Column("updated_by", sa.Uuid(), nullable=True))
    op.alter_column("kb_settings", "self_approval", server_default=sa.false())
    op.execute(_START_COUNTER)


def downgrade() -> None:
    op.execute(_BACK_TO_PREFIX)
    op.alter_column("kb_settings", "self_approval", server_default=sa.true())
    op.drop_column("kb_types", "updated_by")
    op.drop_column("kb_types", "updated_at")
    op.drop_column("kb_types", "version")
