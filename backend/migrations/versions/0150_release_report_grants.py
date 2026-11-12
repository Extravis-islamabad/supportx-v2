"""Reports may read a release's own figures (WP-058b S5b; REQ-REL-060), 0150.

Reports run as supportx_report (SET LOCAL ROLE, ADR-033), which reads only what a migration
grants it. The release source's own fields read the release's details and its approvals'
times. Both grants are COLUMN-level (the coordinator and lane B, #438/S5b): the details without
`release_notes` (free text), the approvals without their comment, decider or route reasons, so a
later report can never read a column nobody granted. RLS still filters by tenant (the role has
no BYPASSRLS). No data step.

Revision ID: 0150
Revises: 0144
Created: 2026-11-12
"""

from collections.abc import Sequence

from migrations.helpers import grant_report_columns, revoke_report

revision: str = "0150"
down_revision: str | None = "0144"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANTS: dict[str, tuple[str, ...]] = {
    "work_item_release_details": (
        "tenant_id",
        "work_item_id",
        "release_type",
        "release_reason",
        "risk",
        "release_version",
        "scheduled_start",
        "scheduled_end",
        "actual_start",
        "actual_end",
        "release_manager_id",
        "release_engineer_id",
    ),
    # Approval turnaround: when it was asked (created_at) and decided; never the comment.
    "work_item_approvals": (
        "tenant_id",
        "id",
        "work_item_id",
        "record_stage",
        "purpose",
        "state",
        "created_at",
        "decided_at",
        "deleted_at",
    ),
}


def upgrade() -> None:
    """Grants the reporting role SELECT on exactly the columns the release source reads."""
    for table, columns in GRANTS.items():
        grant_report_columns(table, columns)


def downgrade() -> None:
    """Takes it back (release measures then refuse again, as before)."""
    for table in GRANTS:
        revoke_report(table)
