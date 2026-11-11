"""Reports may read a change's own figures (WP-045d S4c; REQ-CHG-116).

Reports run as supportx_report (SET LOCAL ROLE, ADR-033), which reads only the tables a
migration grants it. The change source's own fields are correlated subqueries on the change's
details (type, reason, risk, retrospective, freezes passed), its stage schedules (the
implementation's outcome and actual times) and its downtimes (planned and actual). SELECT on
exactly those three tables, nothing broader; RLS still filters by tenant (the role has no
BYPASSRLS). No data step.

Revision ID: 0143
Revises: 0138
Created: 2026-11-11
"""

from collections.abc import Sequence

from migrations.helpers import grant_report, revoke_report

revision: str = "0143"
down_revision: str | None = "0138"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("work_item_change_details", "work_item_stage_schedules", "work_item_downtimes")


def upgrade() -> None:
    """Grants the reporting role SELECT on what the change source's own fields read."""
    for table in TABLES:
        grant_report(table)


def downgrade() -> None:
    """Takes it back (change measures then refuse again, as before)."""
    for table in TABLES:
        revoke_report(table)
