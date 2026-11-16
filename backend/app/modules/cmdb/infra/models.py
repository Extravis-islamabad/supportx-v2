"""CMDB tables (WP-053 S1, migration 0173). All tenant-scoped with RLS forced.

- `cmdb_ci_types`: the CI type tree. Built-in types carry a code (labelled `cmdb_ci_type.<code>`);
  a tenant's own types carry their names per language (`names`).
- `cmdb_ci_states`: CI states, each `active` or `end_of_life` (REQ-CMDB-004).
- `cmdb_cis`: the configuration items. One CI per asset at most (`asset_id` unique); `source`
  says where the CI came from. `custom` (typed JSONB, GIN) is kept for the metadata module's
  custom fields, a follow-up (§6.6, the coordinator 2026-11-16); nothing writes it yet.
- `cmdb_ci_versions`: an append-only snapshot of a CI after every save (REQ-CMDB-024's write
  side), so later sessions can show a CI "as of" a date and build baselines on it.
- `cmdb_settings`: one row per tenant (pickers leave end-of-life CIs out by default).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, Unmapped, mapped_column, unmapped_column

from app.shared.db.models import Base, TenantEntity, TenantKeyed, utc_now

SOURCES = ("manual", "asset_sync", "import", "monetx")
IMPACTS = ("low", "medium", "high", "critical")
CATEGORIES = ("active", "end_of_life")


def _codes(column: str, codes: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


class CiType(TenantEntity):
    """One CI type in the tree (REQ-CMDB-001)."""

    __tablename__ = "cmdb_ci_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_cmdb_ci_types_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["cmdb_ci_types.tenant_id", "cmdb_ci_types.id"],
            name="fk_cmdb_ci_types_parent",
        ),
        CheckConstraint("api_name ~ '^[a-z][a-z0-9_]{1,62}$'", name="api_name_format"),
        Index(
            "uq_cmdb_ci_types_api_name",
            "tenant_id",
            "api_name",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        Index("ix_cmdb_ci_types_tenant_parent", "tenant_id", "parent_id"),
    )

    parent_id: Mapped[uuid.UUID | None]
    api_name: Mapped[str] = mapped_column(String(63))
    built_in: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # A tenant's own type: its name per language ({"en": ..., "ar": ..., "ur": ...}).
    names: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    icon: Mapped[str | None] = mapped_column(String(40))
    # Relationship type codes this type may take part in (S2 fills the catalogue).
    relationship_types: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")


class CiState(TenantEntity):
    """A CI state (REQ-CMDB-004): active, or end of life (kept out of pickers)."""

    __tablename__ = "cmdb_ci_states"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_cmdb_ci_states_tenant_id_id"),
        CheckConstraint("api_name ~ '^[a-z][a-z0-9_]{1,62}$'", name="api_name_format"),
        CheckConstraint(_codes("category", CATEGORIES), name="category_code"),
        Index(
            "uq_cmdb_ci_states_api_name",
            "tenant_id",
            "api_name",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
    )

    api_name: Mapped[str] = mapped_column(String(63))
    built_in: Mapped[bool] = mapped_column(Boolean, server_default="false")
    names: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    category: Mapped[str] = mapped_column(String(20), server_default="active")
    position: Mapped[int] = mapped_column(Integer, server_default="0")


# Search (WP-027 engine): the name, the display ID (also with its dash as a space) and the
# description.
CI_SEARCH_VECTOR = (
    "sx_search_vector(name || ' ' || display_id || ' ' || replace(display_id, '-', ' '),"
    " coalesce(description, ''))"
)


class Ci(TenantEntity):
    """One configuration item (REQ-CMDB-002, 003, 005)."""

    __tablename__ = "cmdb_cis"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_cmdb_cis_tenant_id_id"),
        UniqueConstraint("tenant_id", "display_id", name="uq_cmdb_cis_tenant_id_display_id"),
        ForeignKeyConstraint(
            ["tenant_id", "type_id"],
            ["cmdb_ci_types.tenant_id", "cmdb_ci_types.id"],
            name="fk_cmdb_cis_type",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "state_id"],
            ["cmdb_ci_states.tenant_id", "cmdb_ci_states.id"],
            name="fk_cmdb_cis_state",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "owner_user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_cmdb_cis_owner",
        ),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        CheckConstraint(
            "description IS NULL OR length(description) <= 10000", name="description_length"
        ),
        CheckConstraint(_codes("source", SOURCES), name="source_code"),
        CheckConstraint(
            f"business_impact IS NULL OR {_codes('business_impact', IMPACTS)}",
            name="business_impact_code",
        ),
        CheckConstraint(
            f"criticality IS NULL OR {_codes('criticality', IMPACTS)}", name="criticality_code"
        ),
        # One CI per asset (the asset's record and its CI reconcile into one, file 07 §26).
        Index(
            "uq_cmdb_cis_asset",
            "tenant_id",
            "asset_id",
            unique=True,
            postgresql_where="asset_id IS NOT NULL AND deleted_at IS NULL",
        ),
        Index("ix_cmdb_cis_tenant_updated", "tenant_id", "updated_at", "id"),
        Index("ix_cmdb_cis_tenant_type", "tenant_id", "type_id", "id"),
        Index("ix_cmdb_cis_tenant_state", "tenant_id", "state_id", "id"),
        Index("ix_cmdb_cis_tenant_site", "tenant_id", "site_id", "id"),
        Index("ix_cmdb_cis_tenant_owner", "tenant_id", "owner_user_id"),
        Index("ix_cmdb_cis_tenant_owner_group", "tenant_id", "owner_group_id"),
        Index("ix_cmdb_cis_custom", "custom", postgresql_using="gin"),
        Index("ix_cmdb_cis_search_vector", "search_vector", postgresql_using="gin"),
    )

    display_id: Mapped[str] = mapped_column(String(20))
    type_id: Mapped[uuid.UUID]
    state_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    site_id: Mapped[uuid.UUID | None]
    owner_user_id: Mapped[uuid.UUID | None]
    owner_group_id: Mapped[uuid.UUID | None]
    managed_by_group_id: Mapped[uuid.UUID | None]
    business_impact: Mapped[str | None] = mapped_column(String(20))
    criticality: Mapped[str | None] = mapped_column(String(20))
    asset_id: Mapped[uuid.UUID | None]
    source: Mapped[str] = mapped_column(String(20), server_default="manual")
    custom: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    search_vector: Unmapped[Any] = unmapped_column(
        TSVECTOR, Computed(CI_SEARCH_VECTOR, persisted=True)
    )


class CiVersion(TenantKeyed, Base):
    """A CI as it was after one save (append-only: the app may only read and add)."""

    __tablename__ = "cmdb_ci_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ci_id"],
            ["cmdb_cis.tenant_id", "cmdb_cis.id"],
            name="fk_cmdb_ci_versions_ci",
        ),
        Index("ix_cmdb_ci_versions_ci", "tenant_id", "ci_id", "version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ci_id: Mapped[uuid.UUID]
    version: Mapped[int]
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    saved_at: Mapped[datetime] = mapped_column(server_default=func.now())
    saved_by: Mapped[uuid.UUID | None]


class CmdbSettings(TenantKeyed, Base):
    """Per-tenant CMDB settings (one row, made on first change)."""

    __tablename__ = "cmdb_settings"

    exclude_eol_from_pickers: Mapped[bool] = mapped_column(Boolean, server_default="true")
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=utc_now)
    updated_by: Mapped[uuid.UUID | None]
