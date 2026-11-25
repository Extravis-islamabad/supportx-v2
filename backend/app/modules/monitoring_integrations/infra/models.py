"""MonetX connections, topology runs, mapped devices and links (WP-053 S6; migration 0207).

All tenant-scoped with RLS. A connection's API token is never here: `secret_ref` points into
integrations' connector secrets store. A device's CI is the CMDB's, by ID only (rule e).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import (
    Actors,
    Base,
    TenantEntity,
    TenantScoped,
    Timestamps,
    UuidPrimaryKey,
)


class MonitoringConnection(TenantEntity):
    """One MonetX the tenant reads health and topology from (REQ-INT-040)."""

    __tablename__ = "monitoring_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_monitoring_connections_tenant_id_id"),
        CheckConstraint("kind IN ('monetx')", name="kind_code"),
        CheckConstraint("length(name) BETWEEN 1 AND 120", name="name_length"),
        Index(
            "uq_monitoring_connections_name",
            "tenant_id",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    kind: Mapped[str] = mapped_column(String(20), server_default="monetx")
    name: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(String(500))
    secret_ref: Mapped[uuid.UUID | None]
    tls: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    site_map: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_run_at: Mapped[datetime | None]
    last_error_code: Mapped[str | None] = mapped_column(String(60))


def _connection_fk(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", "connection_id"],
        ["monitoring_connections.tenant_id", "monitoring_connections.id"],
        name=f"fk_{table}_connection",
    )


class TopologyRun(UuidPrimaryKey, TenantScoped, Timestamps, Actors, Base):
    """One topology import of a connection: what it did, by counts, and why it failed (a code)."""

    __tablename__ = "monitoring_topology_runs"
    __table_args__ = (
        _connection_fk("monitoring_topology_runs"),
        CheckConstraint("state IN ('running', 'done', 'failed')", name="state_code"),
        Index(
            "ix_monitoring_topology_runs_tenant_connection",
            "tenant_id",
            "connection_id",
            "started_at",
        ),
    )

    connection_id: Mapped[uuid.UUID]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    state: Mapped[str] = mapped_column(String(20), server_default="running")
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error_code: Mapped[str | None] = mapped_column(String(60))


class MonitoredDevice(UuidPrimaryKey, TenantScoped, Timestamps, Actors, Base):
    """A MonetX device a connection mapped to a CI; stale after 1 missed run, ended after 3."""

    __tablename__ = "monitoring_devices"
    __table_args__ = (
        _connection_fk("monitoring_devices"),
        CheckConstraint("state IN ('seen', 'stale', 'ended')", name="state_code"),
        CheckConstraint("missed_runs >= 0", name="missed_runs"),
        Index(
            "uq_monitoring_devices_external",
            "tenant_id",
            "connection_id",
            "external_id",
            unique=True,
        ),
        Index("ix_monitoring_devices_tenant_ci", "tenant_id", "ci_id"),
    )

    connection_id: Mapped[uuid.UUID]
    external_id: Mapped[str] = mapped_column(String(200))
    ci_id: Mapped[uuid.UUID]
    state: Mapped[str] = mapped_column(String(20), server_default="seen")
    missed_runs: Mapped[int] = mapped_column(Integer, server_default="0")
    last_seen_at: Mapped[datetime | None]
    health: Mapped[str | None] = mapped_column(String(20))
    health_since: Mapped[datetime | None]


class MonitoredLink(UuidPrimaryKey, TenantScoped, Timestamps, Actors, Base):
    """A relationship the import made (so a hand-made one is never removed)."""

    __tablename__ = "monitoring_links"
    __table_args__ = (
        _connection_fk("monitoring_links"),
        Index(
            "uq_monitoring_links_external",
            "tenant_id",
            "connection_id",
            "external_id",
            unique=True,
        ),
    )

    connection_id: Mapped[uuid.UUID]
    external_id: Mapped[str] = mapped_column(String(400))
    relationship_id: Mapped[uuid.UUID]
