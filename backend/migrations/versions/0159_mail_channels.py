"""Mail channels (WP-046a S6; REQ-INC-025, REQ-INC-026, REQ-INC-066), 0159.

Expand only, no data step:
- `mail_block_rules` (RLS): unwanted mail by sender, domain, subject or body text (REQ-INC-026);
- `mail_fetched.outcome` may be `blocked`, and blocked mail waits in the review queue like held
  mail, its copy kept for `mailboxes.quarantine_days` (1 to 90, 14 by default);
- `mailboxes.trusted_servers` (up to 5 host names) and `trust_provider_results` (Microsoft 365
  through Graph): whose Authentication-Results vouch for a sender, so commands written in a mail
  are honoured (REQ-INC-025; lane B's conditions). Empty and off by default: nothing is trusted;
- `work_item_type_settings.mail_commands` (off by default), `mail_command_fields` (which fields a
  mail may set) and `cc_from_first_mail` (on: the first mail's Cc joins the people kept informed);
- `work_items.notify_emails` (up to 20): addresses that get the record's public replies
  (REQ-INC-066);
- `work_item_notify_links` (RLS): a stop-these-mails link per mail sent to such an address; only
  the token's SHA-256 is kept.

The downgrade refuses while any tenant uses any of it (rule 5h): block rules, blocked mail,
trusted servers, mail commands, addresses kept informed or their links.

Revision ID: 0159
Revises: 0157 (re-pointed from 0156 at its queue turn)
Created: 2026-11-13
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0159"
down_revision: str | None = "0157"  # re-pointed from 0156 at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RULES = "mail_block_rules"
LINKS = "work_item_notify_links"
SETTINGS = "work_item_type_settings"
OUTCOMES_BEFORE = (
    "outcome IN ('created', 'replied', 'automatic', 'own_address', 'held', 'rejected',"
    " 'too_large', 'discarded')"
)
OUTCOMES_AFTER = OUTCOMES_BEFORE.replace("'discarded')", "'discarded', 'blocked')")
WAITING_INDEX = "ix_mail_fetched_tenant_waiting"

# Business tables force RLS: the check runs once per tenant (D-113).
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {RULES})
           OR EXISTS (SELECT 1 FROM {LINKS})
           OR EXISTS (SELECT 1 FROM mail_fetched WHERE outcome = 'blocked')
           OR EXISTS (SELECT 1 FROM mailboxes
                      WHERE cardinality(trusted_servers) > 0 OR trust_provider_results
                         OR quarantine_days <> 14)
           OR EXISTS (SELECT 1 FROM {SETTINGS}
                      WHERE mail_commands OR cardinality(mail_command_fields) > 0
                         OR NOT cc_from_first_mail)
           OR EXISTS (SELECT 1 FROM work_items WHERE cardinality(notify_emails) > 0)
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % uses mail channels (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def _stamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
    ]


def _tenant_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{name}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def _rules_table() -> None:
    op.create_table(
        RULES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("value", sa.String(320), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.CheckConstraint(
            "kind IN ('sender', 'domain', 'subject', 'body')", name=op.f(f"ck_{RULES}_kind_code")
        ),
        sa.CheckConstraint(
            "length(btrim(value)) BETWEEN 1 AND 320", name=op.f(f"ck_{RULES}_value_length")
        ),
        _tenant_fk(RULES),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{RULES}")),
    )
    op.create_index(
        "uq_mail_block_rules_tenant_kind_value",
        RULES,
        ["tenant_id", "kind", sa.text("lower(value)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls(RULES)
    enable_actor_audit(RULES)
    grant_app(RULES, ("SELECT", "INSERT", "UPDATE"))


def _links_table() -> None:
    op.create_table(
        LINKS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("address", sa.String(320), nullable=False),
        sa.Column("token_digest", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("octet_length(token_digest) = 32", name=op.f(f"ck_{LINKS}_digest")),
        _tenant_fk(LINKS),
        sa.ForeignKeyConstraint(
            ["tenant_id", "work_item_id"],
            ["work_items.tenant_id", "work_items.id"],
            name="fk_winl_work_item",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{LINKS}")),
    )
    op.create_index("uq_winl_tenant_digest", LINKS, ["tenant_id", "token_digest"], unique=True)
    op.create_index("ix_winl_tenant_expires", LINKS, ["tenant_id", "expires_at"])
    enable_tenant_rls(LINKS)
    grant_app(LINKS, ("SELECT", "INSERT", "UPDATE", "DELETE"))


def _waiting_index(outcomes: str) -> None:
    op.drop_index(WAITING_INDEX, table_name="mail_fetched")
    op.create_index(
        WAITING_INDEX,
        "mail_fetched",
        ["tenant_id", "mailbox_id", "created_at"],
        postgresql_where=sa.text(f"outcome IN ({outcomes})"),
    )


def upgrade() -> None:
    """Block rules, quarantine, trusted servers, mail commands and people kept informed."""
    _rules_table()
    op.drop_constraint(op.f("ck_mail_fetched_outcome_code"), "mail_fetched", type_="check")
    op.create_check_constraint(op.f("ck_mail_fetched_outcome_code"), "mail_fetched", OUTCOMES_AFTER)
    _waiting_index("'held', 'too_large', 'blocked'")
    op.add_column(
        "mailboxes",
        sa.Column(
            "trusted_servers",
            postgresql.ARRAY(sa.String(253)),
            server_default="{}",
            nullable=False,
        ),
    )
    op.add_column(
        "mailboxes",
        sa.Column("trust_provider_results", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "mailboxes",
        sa.Column("quarantine_days", sa.Integer(), server_default="14", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_mailboxes_trusted_servers_max"), "mailboxes", "cardinality(trusted_servers) <= 5"
    )
    op.create_check_constraint(
        op.f("ck_mailboxes_quarantine_days_range"), "mailboxes", "quarantine_days BETWEEN 1 AND 90"
    )
    op.add_column(
        SETTINGS, sa.Column("mail_commands", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column(
        SETTINGS,
        sa.Column(
            "mail_command_fields",
            postgresql.ARRAY(sa.String(30)),
            server_default="{}",
            nullable=False,
        ),
    )
    op.add_column(
        SETTINGS,
        sa.Column("cc_from_first_mail", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "work_items",
        sa.Column(
            "notify_emails", postgresql.ARRAY(sa.String(320)), server_default="{}", nullable=False
        ),
    )
    op.create_check_constraint(
        op.f("ck_work_items_notify_emails_max"), "work_items", "cardinality(notify_emails) <= 20"
    )
    _links_table()


def downgrade() -> None:
    """Back to before (stops while any tenant uses mail channels)."""
    op.execute(GUARD)
    op.drop_table(LINKS)
    op.drop_constraint(op.f("ck_work_items_notify_emails_max"), "work_items", type_="check")
    op.drop_column("work_items", "notify_emails")
    for column in ("cc_from_first_mail", "mail_command_fields", "mail_commands"):
        op.drop_column(SETTINGS, column)
    op.drop_constraint(op.f("ck_mailboxes_quarantine_days_range"), "mailboxes", type_="check")
    op.drop_constraint(op.f("ck_mailboxes_trusted_servers_max"), "mailboxes", type_="check")
    for column in ("quarantine_days", "trust_provider_results", "trusted_servers"):
        op.drop_column("mailboxes", column)
    _waiting_index("'held', 'too_large'")
    op.drop_constraint(op.f("ck_mail_fetched_outcome_code"), "mail_fetched", type_="check")
    op.create_check_constraint(
        op.f("ck_mail_fetched_outcome_code"), "mail_fetched", OUTCOMES_BEFORE
    )
    op.drop_table(RULES)
