"""Reports may read CIs and their relationships (WP-053 S5a, REQ-CMDB-032).

Reports run as supportx_report (SET LOCAL ROLE, ADR-033), which reads only the tables a
migration grants it (as 0124 did for assets). The CMDB's report sources read:
- cmdb_cis: the CI list's own query (`visible_rows`), and the relationship source's both ends;
- cmdb_relationships: the relationship source;
- cmdb_ci_types: a fine-grained access rule on a type takes its subtree (ADR-053), read here.
Compiled for a plain reader and for readers narrowed by a site rule and by a type rule; nothing
else is read under the reporting role (withheld fields are worked out in the app's session).
SELECT only; RLS still filters by tenant. No data step.

Revision ID: 0200
Revises: 0196
Created: 2026-11-24
"""

from collections.abc import Sequence

from migrations.helpers import grant_report, revoke_report

revision: str = "0200"
down_revision: str | None = "0196"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("cmdb_cis", "cmdb_relationships", "cmdb_ci_types")


def upgrade() -> None:
    """Grants the reporting role SELECT on what the CMDB sources read."""
    for table in TABLES:
        grant_report(table)


def downgrade() -> None:
    """Takes it back (CMDB reports then refuse again, as before)."""
    for table in TABLES:
        revoke_report(table)
