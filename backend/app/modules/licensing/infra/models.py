"""Tables owned by the licensing module.

`tenant_subscriptions` is a platform table (allowlisted in tooling/rls_guard.py), like `tenants`:
one row per tenant holding its plan, written by the control plane (today: migrator-role tooling,
`make db-seed`, `make dev-subscription`). RLS is enabled and forced (migration 0005):
- supportx_app may SELECT only its own tenant's row and has no write privilege at all, so no
  request can ever change what a tenant is entitled to;
- supportx_migrator may manage all rows.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import Base, utc_now

EDITION_CODES = ("essentials", "professional", "enterprise")
STATUS_CODES = ("active", "suspended")


class TenantSubscription(Base):
    """A tenant's plan: edition, add-on features, limit overrides and term."""

    __tablename__ = "tenant_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "edition IN (" + ", ".join(f"'{e}'" for e in EDITION_CODES) + ")", name="edition_code"
        ),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in STATUS_CODES) + ")", name="status_code"
        ),
        CheckConstraint("grace_days BETWEEN 0 AND 90", name="grace_days_range"),
        CheckConstraint("jsonb_typeof(limits) = 'object'", name="limits_object"),
        CheckConstraint("expires_at IS NULL OR expires_at > starts_at", name="term_order"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), primary_key=True
    )
    edition: Mapped[str] = mapped_column(String)
    # Add-on features beyond the edition (catalogue keys).
    features: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{}")
    # Overrides of the edition's default limits: {"technicians": 25, "assets": null (unlimited)}.
    limits: Mapped[dict[str, int | None]] = mapped_column(JSONB, server_default="{}")
    starts_at: Mapped[datetime]
    expires_at: Mapped[datetime | None]
    maintenance_until: Mapped[datetime | None]
    grace_days: Mapped[int] = mapped_column(Integer, server_default="14")
    status: Mapped[str] = mapped_column(String, server_default="active")
    version: Mapped[int] = mapped_column(server_default="1")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=utc_now)
    created_by: Mapped[uuid.UUID | None]
    updated_by: Mapped[uuid.UUID | None]
