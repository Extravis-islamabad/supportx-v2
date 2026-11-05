"""Approvals per stage and level, and links of releases (WP-058a s5; REQ-REL-031, -034, -037).

Number from the coordinator; reviewed by lane A for their WP-030 approvals and WP-032 inbox.
Expand only, no data step:
- `work_item_approvals.record_stage`: the stage of a staged record the approval belongs to;
  NULL for service requests, which keep today's behaviour. The existing `stage` stays the level.
- `work_item_approvals.rule`: how the level is decided (any, all, majority); NULL is today's
  behaviour (the first decision decides).
- `work_item_stages.approvals` (JSONB object): a stage's approval settings (REQ-REL-031): the
  status that raises them, the system statuses its outcome sets, and the levels, each with its
  approvers (people, groups, roles) and rule. Checked by the service on save.
- `work_item_links.kind` also accepts `caused_by_release` and `started_release` (an incident,
  request or problem to a release) and `sub_release_of` (a release to its parent), widened
  from the live check (as 0092, 0089), so lanes landing other kinds in either order keep both.

The downgrade drops the two columns and narrows the link check back; while such links exist
the narrowed check fails and the downgrade stops, keeping the data.

Revision ID: 0098
Revises: 0095
Created: 2026-11-05
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0098"
down_revision: str | None = "0095"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPROVALS = "work_item_approvals"
LINK_CHECK = "ck_work_item_links_kind_code"
ADDED_KINDS = ("caused_by_release", "started_release", "sub_release_of")
ROUTE_CHECK = "ck_work_item_approvals_reason_code"
ADDED_REASONS = ("lacks_permission", "no_holder")


def _in(column: str, codes: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def _codes_now(name: str) -> list[str]:
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": name},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(LINK_CHECK), "work_item_links", type_="check")
    op.create_check_constraint(op.f(LINK_CHECK), "work_item_links", _in("kind", codes))


def _recheck_reasons(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(ROUTE_CHECK), APPROVALS, type_="check")
    op.create_check_constraint(
        op.f(ROUTE_CHECK), APPROVALS, "route_reason IS NULL OR " + _in("route_reason", codes)
    )


def upgrade() -> None:
    """The two approval columns and the release link kinds."""
    op.add_column("work_item_stages", sa.Column("approvals", postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        op.f("ck_work_item_stages_approvals_object"),
        "work_item_stages",
        "approvals IS NULL OR jsonb_typeof(approvals) = 'object'",
    )
    op.add_column(APPROVALS, sa.Column("record_stage", sa.String(40), nullable=True))
    op.add_column(APPROVALS, sa.Column("rule", sa.String(10), nullable=True))
    op.create_check_constraint(
        op.f("ck_work_item_approvals_rule_code"),
        APPROVALS,
        "rule IS NULL OR rule IN ('any', 'all', 'majority')",
    )
    # Open approvals of a record's stage, level by level (a staged record's approval panel).
    op.create_index(
        "ix_work_item_approvals_tenant_record_stage",
        APPROVALS,
        ["tenant_id", "work_item_id", "record_stage", "stage"],
        postgresql_where=sa.text("record_stage IS NOT NULL"),
    )
    now = _codes_now(LINK_CHECK)
    _recheck([*now, *(c for c in ADDED_KINDS if c not in now)])
    reasons = _codes_now(ROUTE_CHECK)
    _recheck_reasons([*reasons, *(c for c in ADDED_REASONS if c not in reasons)])


def downgrade() -> None:
    """Back to approvals without stages and links without release kinds (stops while used)."""
    _recheck([c for c in _codes_now(LINK_CHECK) if c not in ADDED_KINDS])
    _recheck_reasons([c for c in _codes_now(ROUTE_CHECK) if c not in ADDED_REASONS])
    op.drop_index("ix_work_item_approvals_tenant_record_stage", table_name=APPROVALS)
    op.drop_constraint(op.f("ck_work_item_approvals_rule_code"), APPROVALS, type_="check")
    op.drop_column(APPROVALS, "rule")
    op.drop_column(APPROVALS, "record_stage")
    op.drop_constraint(
        op.f("ck_work_item_stages_approvals_object"), "work_item_stages", type_="check"
    )
    op.drop_column("work_item_stages", "approvals")
