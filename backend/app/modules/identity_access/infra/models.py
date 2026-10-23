"""Tables owned by identity_access."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import TenantEntity


class User(TenantEntity):
    """A person in one tenant.

    Provisioned just-in-time from the identity provider on login; one row per (tenant, Keycloak
    subject), so a member of two organizations has two rows.
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_subject"),
        UniqueConstraint("tenant_id", "email"),
        CheckConstraint("locale IN ('en', 'ar', 'ur')", name="locale_code"),
        CheckConstraint("status IN ('active', 'disabled')", name="status_code"),
        CheckConstraint("user_type IN ('technician', 'requester')", name="user_type_code"),
        CheckConstraint("char_length(signature) <= 2000", name="signature_length"),
        # Keyset pagination for the sortable columns of GET /users (tenant first, ID last).
        Index("ix_users_tenant_created", "tenant_id", "created_at", "id"),
        Index("ix_users_tenant_display_name", "tenant_id", "display_name", "id"),
        Index("ix_users_tenant_last_login", "tenant_id", "last_login_at", "id"),
    )

    external_subject: Mapped[str]
    email: Mapped[str]
    display_name: Mapped[str]
    locale: Mapped[str] = mapped_column(server_default="en")
    status: Mapped[str] = mapped_column(server_default="active")
    user_type: Mapped[str]
    last_login_at: Mapped[datetime | None]
    # Owned by SupportX, editable by the user (WP-008); identity fields above come from Keycloak.
    signature: Mapped[str | None] = mapped_column(Text)
    time_zone: Mapped[str | None] = mapped_column(String(64))
