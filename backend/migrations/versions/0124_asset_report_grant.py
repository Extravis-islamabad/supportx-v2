"""Reports may read assets (#310's reporting source; lane C found the 500).

Reports run as supportx_report (SET LOCAL ROLE, ADR-033), which reads only the tables a
migration grants it. #310 made assets a reporting source without the grant, so every asset
report answered 500 ("permission denied for table assets"). The source's list query
(`staff_rows`) reads `assets` alone: its scopes compare the row's own columns. SELECT only;
RLS still filters by tenant. No data step.

Revision ID: 0124
Revises: 0115
Created: 2026-11-10
"""

from collections.abc import Sequence

from migrations.helpers import grant_report, revoke_report

revision: str = "0124"
down_revision: str | None = "0115"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("assets",)


def upgrade() -> None:
    """Grants the reporting role SELECT on what the asset source reads."""
    for table in TABLES:
        grant_report(table)


def downgrade() -> None:
    """Takes it back (reports on assets then refuse again, as before)."""
    for table in TABLES:
        revoke_report(table)
