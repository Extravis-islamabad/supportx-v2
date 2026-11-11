"""A change's risk (WP-045b S1; REQ-CHG-056..060), number 0116 from the coordinator.

Expand only, no data step (no assessed change exists before this build):
- `work_item_change_details` gains the calculated risk (`risk`, its `risk_score`, the
  `risk_answers` given and the questionnaire `risk_version` they were scored with, REQ-CHG-057
  AC3) and a person's override (`risk_chosen` with its `risk_reason`, REQ-CHG-060; both
  levels are kept). Levels are checked: low, medium, high, very_high. An override always has
  a reason (a check, as the API says too).
- `work_item_templates.risk_questionnaire` (JSONB, nullable): a template's own questionnaire;
  none means Appendix A's.

The downgrade drops the columns while none holds data; with an assessed or overridden change
it stops and keeps the data (rule 5h).

Revision ID: 0116
Revises: 0124
Created: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0116"
down_revision: str | None = "0124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DETAILS, TEMPLATES = "work_item_change_details", "work_item_templates"
LEVELS = "('low', 'medium', 'high', 'very_high')"
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (
            SELECT 1 FROM {DETAILS} WHERE risk IS NOT NULL OR risk_chosen IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has changes assessed for risk (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - a fixed table name, no input


def upgrade() -> None:
    """The risk columns and the template's questionnaire."""
    op.add_column(DETAILS, sa.Column("risk", sa.String(20), nullable=True))
    op.add_column(DETAILS, sa.Column("risk_score", sa.BigInteger(), nullable=True))
    op.add_column(DETAILS, sa.Column("risk_answers", postgresql.JSONB(), nullable=True))
    op.add_column(DETAILS, sa.Column("risk_version", sa.BigInteger(), nullable=True))
    op.add_column(DETAILS, sa.Column("risk_chosen", sa.String(20), nullable=True))
    op.add_column(DETAILS, sa.Column("risk_reason", sa.String(500), nullable=True))
    op.create_check_constraint(
        op.f(f"ck_{DETAILS}_risk_code"), DETAILS, f"risk IS NULL OR risk IN {LEVELS}"
    )
    op.create_check_constraint(
        op.f(f"ck_{DETAILS}_risk_chosen_code"),
        DETAILS,
        f"risk_chosen IS NULL OR risk_chosen IN {LEVELS}",
    )
    op.create_check_constraint(
        op.f(f"ck_{DETAILS}_override_reason"),
        DETAILS,
        "risk_chosen IS NULL OR (risk_reason IS NOT NULL AND btrim(risk_reason) <> '')",
    )
    op.add_column(TEMPLATES, sa.Column("risk_questionnaire", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    """Back to before risk (stops while a change is assessed or overridden)."""
    # Per tenant with app.tenant_id set: the table forces RLS, so a bare count sees nothing.
    op.execute(GUARD)
    op.drop_column(TEMPLATES, "risk_questionnaire")
    for name in ("override_reason", "risk_chosen_code", "risk_code"):
        op.drop_constraint(op.f(f"ck_{DETAILS}_{name}"), DETAILS, type_="check")
    for column in (
        "risk_reason",
        "risk_chosen",
        "risk_version",
        "risk_answers",
        "risk_score",
        "risk",
    ):
        op.drop_column(DETAILS, column)
