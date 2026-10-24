"""Users: chosen UI language; work item settings: default impact and urgency (WP-020 QA fixes).

- users.ui_locale: the language the user picked in the app (QA BUG-04). NULL means "follow the
  identity provider's locale" (users.locale, refreshed from Keycloak on every login), so the
  choice survives reloads, logins and other devices without being overwritten by the next login.
- work_item_type_settings.default_impact / default_urgency: the values the create form starts
  with (D-070), so the priority shown is the matrix value, never a bare default next to two empty
  fields. Existing rows get the Appendix A defaults (team, medium = P3, the default priority).

Additive with defaults (expand only; reversible).

Revision ID: 0013
Revises: 0012
Created: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCALES = ("en", "ar", "ur")
IMPACTS = ("one_person", "team", "department_or_site", "organisation")
URGENCIES = ("low", "medium", "high", "critical")


def _in(column: str, codes: Sequence[str]) -> str:
    return f"{column} IS NULL OR {column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def upgrade() -> None:
    op.add_column("users", sa.Column("ui_locale", sa.String(), nullable=True))
    op.create_check_constraint(op.f("ck_users_ui_locale_code"), "users", _in("ui_locale", LOCALES))
    op.add_column(
        "work_item_type_settings",
        sa.Column("default_impact", sa.String(30), server_default="team", nullable=True),
    )
    op.add_column(
        "work_item_type_settings",
        sa.Column("default_urgency", sa.String(30), server_default="medium", nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_work_item_type_settings_default_impact_code"),
        "work_item_type_settings",
        _in("default_impact", IMPACTS),
    )
    op.create_check_constraint(
        op.f("ck_work_item_type_settings_default_urgency_code"),
        "work_item_type_settings",
        _in("default_urgency", URGENCIES),
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_work_item_type_settings_default_urgency_code"),
        "work_item_type_settings",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_work_item_type_settings_default_impact_code"),
        "work_item_type_settings",
        type_="check",
    )
    op.drop_column("work_item_type_settings", "default_urgency")
    op.drop_column("work_item_type_settings", "default_impact")
    op.drop_constraint(op.f("ck_users_ui_locale_code"), "users", type_="check")
    op.drop_column("users", "ui_locale")
