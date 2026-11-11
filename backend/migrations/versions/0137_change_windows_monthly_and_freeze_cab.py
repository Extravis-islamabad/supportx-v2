"""Monthly change windows, the outside-maintenance setting, the freeze's emergency CAB (D-156).

Number 0137 (the coordinator, 2026-11-11). Expand only:
- `change_windows.repeat` ('none', 'weekly' or 'monthly'), with `repeat_week` (1 to 4, or 5 for
  the last) and `repeat_weekday` (0 Monday .. 6 Sunday) for a monthly one such as "first
  Sunday". It is filled once per tenant from `repeat_weekly`, which stays for one release
  (expand/contract, architecture.md §14.3) and is kept in step by the service meanwhile.
- `work_item_type_settings.outside_maintenance_blocks`: a change outside every maintenance window
  is refused instead of warned (default off: warn).
- `work_item_change_details.freeze_cab_passed_at`, `freeze_cab_passed_by`: when the emergency CAB
  let an emergency change in a blocking freeze go ahead, and who decided last (the reason is
  the approval's own comment).

The data step runs per tenant with app.tenant_id set, as business tables force RLS (see 0023).
The downgrade drops the columns while no window repeats monthly, no tenant blocks outside
maintenance and no change passed a freeze by its CAB; otherwise it stops and keeps the data
(rule 5h).

Revision ID: 0137
Revises: 0133
Created: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0137"
down_revision: str | None = "0133"  # re-pointed onto main's head at its turn in the queue
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WINDOWS, SETTINGS, DETAILS = "change_windows", "work_item_type_settings", "work_item_change_details"
FILL = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE {WINDOWS} SET repeat = 'weekly' WHERE repeat_weekly AND repeat = 'none';
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {WINDOWS} WHERE repeat = 'monthly')
            OR EXISTS (SELECT 1 FROM {SETTINGS} WHERE outside_maintenance_blocks)
            OR EXISTS (SELECT 1 FROM {DETAILS} WHERE freeze_cab_passed_at IS NOT NULL) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has monthly windows, the outside-maintenance block or a freeze passed by its CAB (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def upgrade() -> None:
    """Add the columns and their checks, then fill `repeat` from the old flag per tenant."""
    op.add_column(
        WINDOWS, sa.Column("repeat", sa.String(10), nullable=False, server_default="none")
    )
    op.add_column(WINDOWS, sa.Column("repeat_week", sa.SmallInteger(), nullable=True))
    op.add_column(WINDOWS, sa.Column("repeat_weekday", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        op.f(f"ck_{WINDOWS}_repeat_code"), WINDOWS, "repeat IN ('none', 'weekly', 'monthly')"
    )
    op.create_check_constraint(
        op.f(f"ck_{WINDOWS}_repeat_monthly_shape"),
        WINDOWS,
        "(repeat = 'monthly') = (repeat_week IS NOT NULL AND repeat_weekday IS NOT NULL)"
        " AND (repeat_week IS NULL OR repeat_week BETWEEN 1 AND 5)"
        " AND (repeat_weekday IS NULL OR repeat_weekday BETWEEN 0 AND 6)",
    )
    op.add_column(
        SETTINGS,
        sa.Column(
            "outside_maintenance_blocks", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        DETAILS, sa.Column("freeze_cab_passed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(DETAILS, sa.Column("freeze_cab_passed_by", sa.Uuid(), nullable=True))
    op.execute(FILL)


def downgrade() -> None:
    """Drop them again while nothing uses them; refuse (and keep the data) otherwise."""
    op.execute(GUARD)
    op.drop_column(DETAILS, "freeze_cab_passed_by")
    op.drop_column(DETAILS, "freeze_cab_passed_at")
    op.drop_column(SETTINGS, "outside_maintenance_blocks")
    op.drop_constraint(op.f(f"ck_{WINDOWS}_repeat_monthly_shape"), WINDOWS, type_="check")
    op.drop_constraint(op.f(f"ck_{WINDOWS}_repeat_code"), WINDOWS, type_="check")
    op.drop_column(WINDOWS, "repeat_weekday")
    op.drop_column(WINDOWS, "repeat_week")
    op.drop_column(WINDOWS, "repeat")
