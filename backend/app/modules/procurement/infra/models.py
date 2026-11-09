"""Procurement tables (WP-049a s2: vendors only; WP-054 adds the rest)."""

from sqlalchemy import Boolean, CheckConstraint, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import TenantEntity


class Vendor(TenantEntity):
    """Someone the tenant buys from or holds contracts with (REQ-PUR-001)."""

    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_vendors_tenant_id_id"),
        CheckConstraint("length(name) BETWEEN 1 AND 200", name="name"),
        CheckConstraint("currency IS NULL OR currency ~ '^[A-Z]{3}$'", name="currency"),
        # Names are unique among the tenant's live vendors, case and spacing aside.
        Index(
            "uq_vendors_name",
            "tenant_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_vendors_name", "tenant_id", "name", "id"),
    )

    name: Mapped[str] = mapped_column(String(200))
    currency: Mapped[str | None] = mapped_column(String(3))
    description: Mapped[str | None] = mapped_column(Text)
    contact_person: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(120))
    fax: Mapped[str | None] = mapped_column(String(120))
    website: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
