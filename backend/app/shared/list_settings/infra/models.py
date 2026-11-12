"""The list-settings table (WP-049b s4a, migration 0140): one row per person, list and view."""

import uuid
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKeyConstraint, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import TenantEntity


class ListSetting(TenantEntity):
    """One person's settings for one view of one list (`list_key`, e.g. `assets`).

    `view_key` is a built-in view code, `all`, or `custom:<id>` for a saved view, which then has
    a `name` and may have a `filter` (the list API's own FilterExpression JSON). `columns` is
    `[{"key": ..., "width": ...}]` (empty: the screen's defaults); `favourite`: starred, shown
    first in the view picker (REQ-INC-107).
    """

    __tablename__ = "list_settings"
    __table_args__ = (
        CheckConstraint("page_size IN (25, 50, 100)", name="page_size_choice"),
        CheckConstraint("jsonb_array_length(columns) <= 40", name="columns_limit"),
        # A saved view has a name; nothing else has one, or a filter.
        CheckConstraint(
            "(name IS NOT NULL) = (view_key LIKE 'custom:%')", name="name_when_saved_view"
        ),
        CheckConstraint(
            "filter IS NULL OR view_key LIKE 'custom:%'", name="filter_when_saved_view"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_list_settings_user"
        ),
        Index(
            "uq_list_settings_user_list_view",
            "tenant_id",
            "user_id",
            "list_key",
            "view_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_list_settings_view_name",
            "tenant_id",
            "user_id",
            "list_key",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND name IS NOT NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID]
    list_key: Mapped[str] = mapped_column(String(60))
    view_key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str | None] = mapped_column(String(120))
    filter: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    sort: Mapped[str | None] = mapped_column(String(200))
    page_size: Mapped[int] = mapped_column(Integer, server_default="50")
    favourite: Mapped[bool] = mapped_column(Boolean, server_default="false")
