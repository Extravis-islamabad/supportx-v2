"""Knowledge tables (WP-033). Every table is tenant-scoped with RLS (migration 0036)."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, Unmapped, mapped_column, unmapped_column

from app.shared.db.models import Base, TenantEntity, TenantKeyed, utc_now

_REQUESTER_AUDIENCE = "requesters IN ('none', 'all', 'selected')"


class KbSettings(TenantKeyed, Base):
    """One row per tenant: knowledge settings (REQ-KB-090), created on first use (D-041)."""

    __tablename__ = "kb_settings"
    __table_args__ = (CheckConstraint("prefix ~ '^[A-Z]{2,6}$'", name="prefix_format"),)

    prefix: Mapped[str] = mapped_column(String(6), server_default="KB")
    self_approval: Mapped[bool] = mapped_column(Boolean, server_default="true")
    requesters_enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=utc_now)
    updated_by: Mapped[uuid.UUID | None]


class KbType(TenantKeyed, Base):
    """A tenant's article type: built-in codes seeded on first use, admins rename and retire."""

    __tablename__ = "kb_types"
    __table_args__ = (
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,39}$'", name="code_format"),
        CheckConstraint("review_months BETWEEN 1 AND 60", name="review_months_range"),
    )

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    # Admin names {"en": ..., "ar": ...}; empty: the built-in label `kb_type.<code>`.
    names: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    review_months: Mapped[int] = mapped_column(SmallInteger)
    builtin: Mapped[bool] = mapped_column(Boolean, server_default="false")
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    retired_at: Mapped[datetime | None]


class KbTopic(TenantEntity):
    """A node of the topic tree (REQ-KB-003, 004) with its audience (REQ-KB-044, 045)."""

    __tablename__ = "kb_topics"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_kb_topics_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["kb_topics.tenant_id", "kb_topics.id"],
            name="fk_kb_topics_parent",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_kb_topics_owner"
        ),
        CheckConstraint("depth BETWEEN 1 AND 6", name="depth_range"),
        CheckConstraint("jsonb_typeof(names) = 'object'", name="names_object"),
        CheckConstraint(
            "description IS NULL OR char_length(description) <= 1000", name="description_length"
        ),
        CheckConstraint(_REQUESTER_AUDIENCE, name="requesters_code"),
        CheckConstraint("tech_all OR cardinality(tech_groups) > 0", name="technicians_not_empty"),
        Index("ix_kb_topics_tenant_parent", "tenant_id", "parent_id", "sort_order"),
    )

    parent_id: Mapped[uuid.UUID | None]
    depth: Mapped[int] = mapped_column(SmallInteger)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    # A name per language {"en": ..., "ar": ...}; readers fall back to English (REQ-KB-003 AC4).
    names: Mapped[dict[str, str]] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(String(40))
    owner_id: Mapped[uuid.UUID | None]
    tech_all: Mapped[bool] = mapped_column(Boolean, server_default="true")
    tech_groups: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default="{}")
    requesters: Mapped[str] = mapped_column(String(10), server_default="none")
    req_groups: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default="{}")
    req_sites: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default="{}")
    req_departments: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default="{}")


class KbArticle(TenantEntity):
    """An article: what all its versions and translations share (REQ-KB-001)."""

    __tablename__ = "kb_articles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_kb_articles_tenant_id_id"),
        UniqueConstraint("tenant_id", "display_id", name="uq_kb_articles_tenant_display_id"),
        ForeignKeyConstraint(
            ["tenant_id", "topic_id"],
            ["kb_topics.tenant_id", "kb_topics.id"],
            name="fk_kb_articles_topic",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "type_code"],
            ["kb_types.tenant_id", "kb_types.code"],
            name="fk_kb_articles_type",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_kb_articles_owner"
        ),
        CheckConstraint("default_language IN ('en', 'ar')", name="default_language_code"),
        CheckConstraint(f"own_audience = false OR ({_REQUESTER_AUDIENCE})", name="requesters_code"),
        CheckConstraint(
            "expires_on IS NULL OR review_on IS NULL OR expires_on > review_on",
            name="expiry_after_review",
        ),
        CheckConstraint(
            "withdrawn_reason IS NULL OR char_length(withdrawn_reason) <= 1000",
            name="withdrawn_reason_length",
        ),
        Index("ix_kb_articles_tenant_topic", "tenant_id", "topic_id", "updated_at", "id"),
        Index("ix_kb_articles_tenant_owner", "tenant_id", "owner_id", "updated_at", "id"),
        Index(
            "ix_kb_articles_tenant_review",
            "tenant_id",
            "review_on",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    display_id: Mapped[str] = mapped_column(String(30))
    topic_id: Mapped[uuid.UUID]
    type_code: Mapped[str] = mapped_column(String(40))
    owner_id: Mapped[uuid.UUID]
    default_language: Mapped[str] = mapped_column(String(5), server_default="en")
    # Its own (narrower) audience; false: the topic's (REQ-KB-044).
    own_audience: Mapped[bool] = mapped_column(Boolean, server_default="false")
    tech_all: Mapped[bool] = mapped_column(Boolean, server_default="true")
    tech_groups: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default="{}")
    requesters: Mapped[str] = mapped_column(String(10), server_default="none")
    req_groups: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default="{}")
    req_sites: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default="{}")
    req_departments: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default="{}")
    review_on: Mapped[date | None]
    expires_on: Mapped[date | None]
    withdrawn_reason: Mapped[str | None] = mapped_column(Text)
    withdrawn_at: Mapped[datetime | None]


class KbArticleVersion(TenantEntity):
    """One version of one language of an article (REQ-KB-020, 021, 049).

    Drafts are edited in place (autosave, with If-Match on `version`); published and superseded
    versions never change (a trigger refuses it, REQ-KB-020 AC2).
    """

    __tablename__ = "kb_article_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_kb_article_versions_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "article_id"],
            ["kb_articles.tenant_id", "kb_articles.id"],
            name="fk_kb_article_versions_article",
        ),
        CheckConstraint("language IN ('en', 'ar')", name="language_code"),
        CheckConstraint(
            "status IN ('draft', 'in_review', 'published', 'superseded', 'rejected')",
            name="status_code",
        ),
        CheckConstraint("length(btrim(title)) BETWEEN 1 AND 250", name="title_length"),
        CheckConstraint("char_length(body_html) <= 500000", name="body_length"),
        CheckConstraint("cardinality(keywords) <= 30", name="keywords_count"),
        CheckConstraint(
            "internal_note IS NULL OR char_length(internal_note) <= 2000", name="note_length"
        ),
        CheckConstraint(
            "change_note IS NULL OR char_length(change_note) <= 500", name="change_note_length"
        ),
        CheckConstraint(
            "reject_reason IS NULL OR char_length(reject_reason) <= 2000",
            name="reject_reason_length",
        ),
        # One published version and one open draft (draft or in review) per article language.
        Index(
            "uq_kb_versions_published",
            "tenant_id",
            "article_id",
            "language",
            unique=True,
            postgresql_where=text("status = 'published' AND deleted_at IS NULL"),
        ),
        Index(
            "uq_kb_versions_open",
            "tenant_id",
            "article_id",
            "language",
            unique=True,
            postgresql_where=text("status IN ('draft', 'in_review') AND deleted_at IS NULL"),
        ),
        Index("ix_kb_versions_tenant_article", "tenant_id", "article_id", "language", "number"),
        Index("ix_kb_versions_search", "search_vector", postgresql_using="gin"),
        Index(
            "ix_kb_versions_search_title",
            "search_title",
            postgresql_using="gin",
            postgresql_ops={"search_title": "gin_trgm_ops"},
        ),
    )

    article_id: Mapped[uuid.UUID]
    language: Mapped[str] = mapped_column(String(5))
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), server_default="draft")
    title: Mapped[str] = mapped_column(String(250))
    body_html: Mapped[str] = mapped_column(Text, server_default="")  # sanitised (REQ-KB-006)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String(60)), server_default="{}")
    change_note: Mapped[str | None] = mapped_column(Text)
    internal_note: Mapped[str | None] = mapped_column(Text)  # never to readers (REQ-KB-001 AC2)
    submitted_by: Mapped[uuid.UUID | None]
    submitted_at: Mapped[datetime | None]
    decided_by: Mapped[uuid.UUID | None]
    decided_at: Mapped[datetime | None]
    reject_reason: Mapped[str | None] = mapped_column(Text)
    self_approved: Mapped[bool] = mapped_column(Boolean, server_default="false")
    published_at: Mapped[datetime | None]
    # Search (WP-027 port): title, keywords and the body's text, normalised by the database.
    # A column of the table, not of the mapped object: never loaded or written by the ORM.
    search_vector: Unmapped[Any] = unmapped_column(
        TSVECTOR,
        Computed(
            "sx_search_vector(title || ' ' || kb_keywords_text(keywords), "
            "regexp_replace(body_html, '<[^>]*>|&[a-zA-Z0-9#]+;', ' ', 'g'))",
            persisted=True,
        ),
    )
    search_title: Unmapped[str] = unmapped_column(
        Text, Computed("sx_search_normalize(title)", persisted=True)
    )


class KbReview(TenantEntity):
    """One "still correct" review: checked, review date moved forward, no new version.

    REQ-KB-034: the history of who checked an article and when.
    """

    __tablename__ = "kb_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "article_id"],
            ["kb_articles.tenant_id", "kb_articles.id"],
            name="fk_kb_reviews_article",
        ),
        Index(None, "tenant_id", "article_id", "created_at"),
    )

    article_id: Mapped[uuid.UUID]
    reviewed_by: Mapped[uuid.UUID]
    next_review_on: Mapped[date]
