"""SIEM syslog transports (D-181): TLS by default, plain TCP or UDP only when an admin opts in.

- siem_destinations.transport: tls | tcp | udp. Every existing destination is tls (the server
  default fills them). A webhook is always tls (HTTPS).
- siem_destinations.udp_max_bytes: the largest datagram a UDP destination is sent (2,048 bytes by
  default, 480 to 8,192); a longer entry is sent cut with a visible marker, never silently.

Revision ID: 0190
Revises: 0185
Created: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0190"
down_revision: str | None = "0185"  # main's head now; re-pointed at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "siem_destinations"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("transport", sa.String(length=8), server_default="tls", nullable=False),
    )
    op.add_column(
        TABLE,
        sa.Column("udp_max_bytes", sa.Integer(), server_default="2048", nullable=False),
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_transport_code"), TABLE, "transport IN ('tls', 'tcp', 'udp')"
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_webhook_tls"), TABLE, "kind = 'syslog' OR transport = 'tls'"
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_udp_max_range"), TABLE, "udp_max_bytes BETWEEN 480 AND 8192"
    )


def downgrade() -> None:
    op.drop_constraint(op.f(f"ck_{TABLE}_udp_max_range"), TABLE, type_="check")
    op.drop_constraint(op.f(f"ck_{TABLE}_webhook_tls"), TABLE, type_="check")
    op.drop_constraint(op.f(f"ck_{TABLE}_transport_code"), TABLE, type_="check")
    op.drop_column(TABLE, "udp_max_bytes")
    op.drop_column(TABLE, "transport")
