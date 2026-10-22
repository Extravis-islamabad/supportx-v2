"""Tables owned by the organization module.

`tenants` is a platform table, not a tenant-scoped one: its `id` *is* the tenant. RLS is still
enabled and forced on it (migration 0001):
- supportx_app may SELECT only the row whose id equals the transaction's `app.tenant_id`, and has
  no INSERT/UPDATE/DELETE privilege at all;
- supportx_migrator (provisioning, seeding) may manage all rows.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.organization.domain.tenant import SLUG_PATTERN
from app.shared.db.models import Base, UuidPrimaryKey


class Tenant(UuidPrimaryKey, Base):
    """A customer organisation (one row per tenant)."""

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(f"slug ~ '{SLUG_PATTERN}'", name="slug_format"),
        CheckConstraint("status IN ('active', 'suspended')", name="status_code"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
    )

    name: Mapped[str]
    slug: Mapped[str] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(server_default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
