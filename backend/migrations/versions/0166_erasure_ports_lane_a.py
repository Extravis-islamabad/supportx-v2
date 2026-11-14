"""Lane A's erasure ports (ADR-052 §4; D-171), 0166.

Expand only, no data step:
- DELETE for the app role on eight tables of a person's private rows. Erasure removes those for
  good (CLAUDE.md §6: a hard delete only through erasure; a soft delete still holds the data).
  Everywhere else they stay soft-deleted or kept: tests/test_erasure_deletes_lane_a.py fails on
  a DELETE outside the erasure ports and the purges already there.
- `approver_erased`, a reason an approval went to the approval administrators: an erased
  approver's pending approvals are rerouted, never granted (the coordinator, 2026-11-14).
- Two indexes on work_items for the erasure's "records this person requested" (lane B's #504
  note): requester and on-behalf-of, each led by the tenant. work_items is large, so both are
  built CONCURRENTLY (no write lock), outside the migration's transaction, as 0135 does.

The downgrade puts the old grants back and drops the indexes (neither holds data); it refuses
while any tenant has an approval rerouted for an erased approver (rule 5h).

Revision ID: 0166
Revises: 0163
Created: 2026-11-14
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import grant_app

revision: str = "0166"
down_revision: str | None = "0163"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Today SELECT, INSERT, UPDATE only (soft delete); erasure needs DELETE too.
PRIVATE_TABLES = (
    "work_item_followers",
    "work_item_list_settings",
    "work_item_reminders",
    "work_item_timers",
    "work_item_views",
    "work_item_reply_templates",
    "notification_preferences",
    "technician_availability",
)
APPROVALS, REASON_CHECK = "work_item_approvals", "ck_work_item_approvals_reason_code"
ADDED_REASONS = ("approver_erased",)
REQUESTER_INDEX = "ix_wi_tenant_requester_id"
ON_BEHALF_INDEX = "ix_wi_tenant_on_behalf_id"


# Business tables force RLS: the check runs once per tenant (D-113).
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {APPROVALS} WHERE route_reason = 'approver_erased') THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has approvals of erased approvers', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed names, no input


def _reasons_now() -> list[str]:
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": REASON_CHECK},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(REASON_CHECK), APPROVALS, type_="check")
    listed = ", ".join(f"'{c}'" for c in codes)
    op.create_check_constraint(
        op.f(REASON_CHECK),
        APPROVALS,
        f"route_reason IS NULL OR route_reason IN ({listed})",
    )


def upgrade() -> None:
    """The DELETE grants, the new reason, then the two indexes (concurrently)."""
    for table in PRIVATE_TABLES:
        grant_app(table)  # SELECT, INSERT, UPDATE, DELETE
    now = _reasons_now()
    _recheck([*now, *(c for c in ADDED_REASONS if c not in now)])
    # CONCURRENTLY cannot run inside a transaction block: alembic's autocommit block.
    with op.get_context().autocommit_block():
        op.create_index(
            REQUESTER_INDEX,
            "work_items",
            ["tenant_id", "requester_id", "id"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            ON_BEHALF_INDEX,
            "work_items",
            ["tenant_id", "on_behalf_of_id", "id"],
            postgresql_where="on_behalf_of_id IS NOT NULL",
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    """Back to before (stops while an approval was rerouted for an erased approver)."""
    op.execute(GUARD)
    _recheck([c for c in _reasons_now() if c not in ADDED_REASONS])
    with op.get_context().autocommit_block():
        op.drop_index(
            ON_BEHALF_INDEX, table_name="work_items", postgresql_concurrently=True, if_exists=True
        )
        op.drop_index(
            REQUESTER_INDEX, table_name="work_items", postgresql_concurrently=True, if_exists=True
        )
    for table in PRIVATE_TABLES:
        grant_app(table, ("SELECT", "INSERT", "UPDATE"))
