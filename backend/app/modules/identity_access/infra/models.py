"""Tables owned by identity_access."""

from datetime import datetime

from sqlalchemy import CheckConstraint, UniqueConstraint
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
    )

    external_subject: Mapped[str]
    email: Mapped[str]
    display_name: Mapped[str]
    locale: Mapped[str] = mapped_column(server_default="en")
    status: Mapped[str] = mapped_column(server_default="active")
    user_type: Mapped[str]
    last_login_at: Mapped[datetime | None]
