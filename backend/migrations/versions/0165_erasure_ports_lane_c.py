"""DELETE for the GDPR erasure ports of knowledge and analytics (ADR-052 S2; lane C).

The erasure is the one place a hard delete is allowed (CLAUDE.md §6, D-171): a person's votes
(with their comments), dashboard preferences, report exports and private dashboards go for good (reports and folders are shared at MVP: they move to the successor).
Everywhere else these tables stay soft-delete or append-only: `tests/test_erasure_deletes.py` fails if any code path other than the erasure ports
issues a DELETE on them (the coordinator's condition). AI calls are not here: their rows are
the usage and cost record, so the ai port only clears their text (lane B, #502).

Grants only, through migrations/helpers.py; no data step. The downgrade takes DELETE away again.

Revision ID: 0165
Revises: 0163
Created: 2026-11-14
"""

from collections.abc import Sequence

from migrations.helpers import grant_app

revision: str = "0165"
down_revision: str | None = "0163"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Each table's grants before this migration (what the downgrade puts back).
BEFORE: dict[str, tuple[str, ...]] = {
    "kb_votes": ("SELECT", "INSERT", "UPDATE"),
    "dashboard_preferences": ("SELECT", "INSERT", "UPDATE"),
    "report_exports": ("SELECT", "INSERT", "UPDATE"),
    "dashboards": ("SELECT", "INSERT", "UPDATE"),
}


def upgrade() -> None:
    """DELETE added to each table's grants (the erasure ports' hard delete)."""
    for table, privileges in BEFORE.items():
        grant_app(table, (*privileges, "DELETE"))


def downgrade() -> None:
    """Back to the grants before (grant_app revokes all first, so DELETE goes)."""
    for table, privileges in BEFORE.items():
        grant_app(table, privileges)
