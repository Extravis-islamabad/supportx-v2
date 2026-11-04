"""The action link table (WP-030 s3, REQ-NTF-024): one row per link, by its token's digest."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import TenantEntity


class ActionLink(TenantEntity):
    """A one-time link for one recipient to take one action on one object at one version.

    Only the SHA-256 of the token is kept (`token_digest`); the token itself exists only in
    the message that carried it.
    """

    __tablename__ = "action_links"
    __table_args__ = (
        Index("uq_action_links_tenant_digest", "tenant_id", "token_digest", unique=True),
        Index("ix_action_links_tenant_object", "tenant_id", "object_type", "object_id"),
        CheckConstraint("octet_length(token_digest) = 32", name="digest_length"),
        CheckConstraint("object_version >= 1", name="version_positive"),
    )

    token_digest: Mapped[bytes] = mapped_column(LargeBinary)
    recipient_id: Mapped[uuid.UUID]
    action: Mapped[str] = mapped_column(String(60))
    object_type: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[uuid.UUID]
    object_version: Mapped[int]
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    used_by: Mapped[uuid.UUID | None]
    revoked_at: Mapped[datetime | None]
