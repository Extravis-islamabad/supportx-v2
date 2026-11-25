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

S2 (0180): relationship types and their rules, relationships, business views.
S4a (0191): each CI attribute's source and time (`cmdb_cis.sources`), which source wins
(`cmdb_settings.source_precedence`), sync rules from assets and their runs.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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
    text,
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
    # Each attribute's source and time, {attribute: {source, at}} (REQ-CMDB-016, 0191): set by
    # the path that wrote the value, never by a client.
    sources: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
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
    # Which source wins, {order, overrides} (REQ-CMDB-016, 0191); empty: the defaults.
    source_precedence: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=utc_now)
    updated_by: Mapped[uuid.UUID | None]


# --- relationships and business views (WP-053 S2, migration 0180) ---------------------------------

LAYOUTS = ("radial", "hierarchical", "tree")


class RelationshipType(TenantEntity):
    """A named link between CIs, one name per direction (REQ-CMDB-006).

    A built-in type is labelled `cmdb_relationship.<code>.forward|inverse`; a tenant's own type
    carries both names per language. `carries_impact` says whether impact flows through it.
    """

    __tablename__ = "cmdb_relationship_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_cmdb_relationship_types_tenant_id_id"),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,62}$'", name="code_format"),
        Index(
            "uq_cmdb_relationship_types_code",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
    )

    code: Mapped[str] = mapped_column(String(63))
    built_in: Mapped[bool] = mapped_column(Boolean, server_default="false")
    names_forward: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    names_inverse: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    carries_impact: Mapped[bool] = mapped_column(Boolean, server_default="true")


class RelationshipTypeRule(TenantEntity):
    """The CI types a relationship type may join (a rule on a type covers the types below it)."""

    __tablename__ = "cmdb_relationship_type_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "type_id"],
            ["cmdb_relationship_types.tenant_id", "cmdb_relationship_types.id"],
            name="fk_cmdb_relationship_type_rules_type",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "from_ci_type_id"],
            ["cmdb_ci_types.tenant_id", "cmdb_ci_types.id"],
            name="fk_cmdb_relationship_type_rules_from",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "to_ci_type_id"],
            ["cmdb_ci_types.tenant_id", "cmdb_ci_types.id"],
            name="fk_cmdb_relationship_type_rules_to",
        ),
        Index(
            "uq_cmdb_relationship_type_rules_pair",
            "tenant_id",
            "type_id",
            "from_ci_type_id",
            "to_ci_type_id",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
    )

    type_id: Mapped[uuid.UUID]
    from_ci_type_id: Mapped[uuid.UUID]
    to_ci_type_id: Mapped[uuid.UUID]
    suggested: Mapped[bool] = mapped_column(Boolean, server_default="false")


class Relationship(TenantEntity):
    """One link "from runs on to" (REQ-CMDB-007). Never edited; removal is a soft delete."""

    __tablename__ = "cmdb_relationships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "type_id"],
            ["cmdb_relationship_types.tenant_id", "cmdb_relationship_types.id"],
            name="fk_cmdb_relationships_type",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "from_ci_id"],
            ["cmdb_cis.tenant_id", "cmdb_cis.id"],
            name="fk_cmdb_relationships_from",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "to_ci_id"],
            ["cmdb_cis.tenant_id", "cmdb_cis.id"],
            name="fk_cmdb_relationships_to",
        ),
        CheckConstraint("from_ci_id <> to_ci_id", name="not_self"),
        Index(
            "uq_cmdb_relationships_live",
            "tenant_id",
            "type_id",
            "from_ci_id",
            "to_ci_id",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        Index("ix_cmdb_relationships_tenant_from", "tenant_id", "from_ci_id"),
        Index("ix_cmdb_relationships_tenant_to", "tenant_id", "to_ci_id"),
    )

    type_id: Mapped[uuid.UUID]
    from_ci_id: Mapped[uuid.UUID]
    to_ci_id: Mapped[uuid.UUID]


class BusinessView(TenantEntity):
    """A saved map for one base CI (REQ-CMDB-009): layout, filters and pinned positions."""

    __tablename__ = "cmdb_business_views"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "base_ci_id"],
            ["cmdb_cis.tenant_id", "cmdb_cis.id"],
            name="fk_cmdb_business_views_base",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["users.tenant_id", "users.id"],
            name="fk_cmdb_business_views_owner",
        ),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        CheckConstraint(
            "description IS NULL OR length(description) <= 10000", name="description_length"
        ),
        CheckConstraint(_codes("layout", LAYOUTS), name="layout_code"),
        Index("ix_cmdb_business_views_tenant_updated", "tenant_id", "updated_at", "id"),
        Index("ix_cmdb_business_views_tenant_base", "tenant_id", "base_ci_id"),
        Index("ix_cmdb_business_views_tenant_owner", "tenant_id", "owner_id"),
    )

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    base_ci_id: Mapped[uuid.UUID]
    layout: Mapped[str] = mapped_column(String(20), server_default="radial")
    # The map's filters: relationship type IDs, CI type IDs, show end of life, depth.
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    # Pinned nodes by CI ID, each an x and a y (a restricted node is never pinned).
    positions: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    owner_id: Mapped[uuid.UUID | None]


class ServiceSubscriber(TenantEntity):
    """A department, site or group a business service serves (WP-053, D-172 (3); 0185).

    No foreign key to the unit: one removed later stays here, shown "removed", counting nobody.
    """

    __tablename__ = "cmdb_service_subscribers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ci_id"],
            ["cmdb_cis.tenant_id", "cmdb_cis.id"],
            name="fk_cmdb_service_subscribers_ci",
        ),
        CheckConstraint("kind IN ('department', 'site', 'group')", name="kind_code"),
        Index(
            "uq_cmdb_service_subscribers_live",
            "tenant_id",
            "ci_id",
            "kind",
            "ref_id",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        Index("ix_cmdb_service_subscribers_tenant_ref", "tenant_id", "kind", "ref_id"),
    )

    ci_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(String(20))
    ref_id: Mapped[uuid.UUID]


# --- CI downtimes (WP-053 S5b, REQ-CMDB-020; migration 0198) -------------------------------------

DOWNTIME_SOURCES = ("change", "release", "incident", "manual")
DOWNTIME_STATES = ("scheduled", "active", "completed")
DOWNTIME_PHASES = ("planned", "actual")


class CiDowntime(TenantEntity):
    """One downtime of one CI: from work_items (a change's, a release's, an incident's) or by hand.

    A synced row is keyed by (source downtime, CI) and kept in step by `work_items.downtime.
    changed`, never edited here; `source_version` drops a replayed or out-of-order event. Only a
    `manual` row carries a description (a synced one shows its source record instead). `state`
    is moved by the one-minute sweep as time passes (REQ-CMDB-020 AC1).
    """

    __tablename__ = "cmdb_ci_downtimes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ci_id"],
            ["cmdb_cis.tenant_id", "cmdb_cis.id"],
            name="fk_cmdb_ci_downtimes_ci",
        ),
        CheckConstraint(
            "source IN ('change', 'release', 'incident', 'manual')", name="source_code"
        ),
        CheckConstraint("state IN ('scheduled', 'active', 'completed')", name="state_code"),
        CheckConstraint("phase IN ('planned', 'actual')", name="phase_code"),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ends_after_start"),
        # A synced row names its source; a hand-recorded one never does.
        CheckConstraint("(source = 'manual') = (source_downtime_id IS NULL)", name="source_ref"),
        Index(
            "uq_cmdb_ci_downtimes_source",
            "tenant_id",
            "source_downtime_id",
            "ci_id",
            unique=True,
            postgresql_where="deleted_at IS NULL AND source_downtime_id IS NOT NULL",
        ),
        Index("ix_cmdb_ci_downtimes_tenant_ci", "tenant_id", "ci_id", "starts_at"),
        Index(
            "ix_cmdb_ci_downtimes_tenant_sweep",
            "tenant_id",
            "state",
            "starts_at",
            postgresql_where="deleted_at IS NULL AND state <> 'completed'",
        ),
    )

    ci_id: Mapped[uuid.UUID]
    source: Mapped[str] = mapped_column(String(20))
    source_work_item_id: Mapped[uuid.UUID | None]
    source_downtime_id: Mapped[uuid.UUID | None]
    source_version: Mapped[int | None]
    phase: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str | None] = mapped_column(String(40))
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime | None]
    description: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), server_default="scheduled")


# --- sync rules and their runs (WP-053 S4a, migration 0191) ---------------------------------------

SYNC_SOURCES = ("assets",)
SYNC_TRIGGERS = ("schedule", "manual", "asset_changed")
SYNC_STATUSES = ("queued", "running", "succeeded", "failed")


class SyncRule(TenantEntity):
    """Which assets become CIs of which type, and how their fields map (REQ-CMDB-015)."""

    __tablename__ = "cmdb_sync_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_cmdb_sync_rules_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "target_type_id"],
            ["cmdb_ci_types.tenant_id", "cmdb_ci_types.id"],
            name="fk_cmdb_sync_rules_type",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "target_state_id"],
            ["cmdb_ci_states.tenant_id", "cmdb_ci_states.id"],
            name="fk_cmdb_sync_rules_state",
        ),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        CheckConstraint(_codes("source_kind", SYNC_SOURCES), name="source_kind_code"),
        Index(
            "uq_cmdb_sync_rules_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        Index("ix_cmdb_sync_rules_tenant_updated", "tenant_id", "updated_at", "id"),
    )

    name: Mapped[str] = mapped_column(String(200))
    source_kind: Mapped[str] = mapped_column(String(20), server_default="assets")
    # The assets it selects, in the asset list's DSL (assets' sync filter fields); None: all.
    filter: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    target_type_id: Mapped[uuid.UUID]
    target_state_id: Mapped[uuid.UUID | None]
    # CI attribute → asset field (only assets' syncable fields).
    field_map: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")


class SyncRun(TenantEntity):
    """One run of a rule: its counts and a capped list of what it did per asset.

    Written by the worker only (never edited through the API). An incremental run (an asset
    changed) lists the assets to re-read in `asset_ids`; a full run reads every match.
    """

    __tablename__ = "cmdb_sync_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "rule_id"],
            ["cmdb_sync_rules.tenant_id", "cmdb_sync_rules.id"],
            name="fk_cmdb_sync_runs_rule",
        ),
        CheckConstraint(_codes("trigger", SYNC_TRIGGERS), name="trigger_code"),
        CheckConstraint(_codes("status", SYNC_STATUSES), name="status_code"),
        Index("ix_cmdb_sync_runs_tenant_rule", "tenant_id", "rule_id", "created_at"),
        Index(
            "ix_cmdb_sync_runs_tenant_open",
            "tenant_id",
            "created_at",
            postgresql_where="status IN ('queued', 'running')",
        ),
    )

    rule_id: Mapped[uuid.UUID]
    trigger: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), server_default="queued")
    asset_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]
    created_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    updated_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    kept_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    unchanged_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    failed_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    # At most OUTCOMES_MAX: {asset_id, ci_id, outcome, kept: [attributes], code}. IDs and codes
    # only; names are looked up when read, through the reader's view.
    outcomes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    # The rule's custom targets this run skipped (no longer a plain field); keys only.
    skipped_targets: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    failure: Mapped[str | None] = mapped_column(String(60))


# --- merges and imports (WP-053 S4b, migration 0192) ----------------------------------------------

IMPORT_KINDS = ("cis", "relationships")
IMPORT_MODES = ("add", "update", "add_update")
IMPORT_MATCHES = ("display_id", "name")
IMPORT_STATUSES = ("queued", "running", "checked", "done", "failed")


class CiAlias(TenantEntity):
    """One CI merged into another (REQ-CMDB-017), and the alias it leaves.

    The merged CI (`alias_id`) is in the trash. Its ID and display ID find the survivor
    (`ci_id`), but only for a reader who may see the survivor. `mapping` is the field-by-field
    choice ([{"field", "side"}], codes only); `moved` counts what moved. A restore of the merged CI
    ends the alias (`restored_at`); it never undoes the merge.
    """

    __tablename__ = "cmdb_ci_aliases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "alias_id"],
            ["cmdb_cis.tenant_id", "cmdb_cis.id"],
            name="fk_cmdb_ci_aliases_alias",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ci_id"],
            ["cmdb_cis.tenant_id", "cmdb_cis.id"],
            name="fk_cmdb_ci_aliases_ci",
        ),
        CheckConstraint("alias_id <> ci_id", name="not_self"),
        Index(
            "uq_cmdb_ci_aliases_live",
            "tenant_id",
            "alias_id",
            unique=True,
            postgresql_where="restored_at IS NULL AND deleted_at IS NULL",
        ),
        Index("ix_cmdb_ci_aliases_tenant_ci", "tenant_id", "ci_id"),
        Index("ix_cmdb_ci_aliases_tenant_display", "tenant_id", text("lower(alias_display_id)")),
    )

    alias_id: Mapped[uuid.UUID]
    ci_id: Mapped[uuid.UUID]
    alias_display_id: Mapped[str] = mapped_column(String(20))
    mapping: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    moved: Mapped[dict[str, int]] = mapped_column(JSONB, server_default="{}")
    restored_at: Mapped[datetime | None]
    restored_by: Mapped[uuid.UUID | None]


class CiImport(TenantEntity):
    """One CSV or Excel file of CIs or relationships (REQ-CMDB-018), read in the background.

    A dry run reads and checks every row inside savepoints it rolls back, so nothing changes; it
    ends `checked`, keeping the file for the real run. The file is cleared once the real run has
    read it. Results keep counts and per-row problems (row, column, code), never values.
    """

    __tablename__ = "cmdb_imports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "type_id"],
            ["cmdb_ci_types.tenant_id", "cmdb_ci_types.id"],
            name="fk_cmdb_imports_type",
        ),
        CheckConstraint(_codes("kind", IMPORT_KINDS), name="kind_code"),
        CheckConstraint(_codes("mode", IMPORT_MODES), name="mode_code"),
        CheckConstraint(_codes("match_on", IMPORT_MATCHES), name="match_code"),
        CheckConstraint(_codes("status", IMPORT_STATUSES), name="status_code"),
        CheckConstraint("kind <> 'cis' OR type_id IS NOT NULL", name="cis_have_a_type"),
        Index("ix_cmdb_imports_requested", "tenant_id", "created_by", "created_at"),
        Index(
            "ix_cmdb_imports_pending",
            "tenant_id",
            "created_at",
            postgresql_where="status IN ('queued', 'running') AND deleted_at IS NULL",
        ),
    )

    kind: Mapped[str] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(20))
    match_on: Mapped[str] = mapped_column(String(20))
    type_id: Mapped[uuid.UUID | None]
    dry_run: Mapped[bool] = mapped_column(Boolean, server_default="true")
    file_name: Mapped[str] = mapped_column(String(255))
    file_format: Mapped[str] = mapped_column(String(10))
    content: Mapped[bytes | None]
    status: Mapped[str] = mapped_column(String(20), server_default="queued")
    total: Mapped[int] = mapped_column(Integer, server_default="0")
    processed: Mapped[int] = mapped_column(Integer, server_default="0")
    created_count: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_count: Mapped[int] = mapped_column(Integer, server_default="0")
    unchanged_count: Mapped[int] = mapped_column(Integer, server_default="0")
    # Rows that changed nothing because a stronger source set the values (S4a's who wins).
    kept_count: Mapped[int] = mapped_column(Integer, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, server_default="0")
    # [{"row": 12, "field": "to", "code": "not_found"}, ...] (codes only, never values).
    problems: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    failure: Mapped[str | None] = mapped_column(String(50))
    failure_detail: Mapped[str | None] = mapped_column(String(100))
    checked_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
