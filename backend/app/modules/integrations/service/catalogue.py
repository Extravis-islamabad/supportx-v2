"""The connector catalogue (WP-040 session 1; REQ-INT-001, REQ-INT-013).

One list of every integration the tenant can use, grouped by category, with each instance's live
status. Kinds come from the shared registry (`app.shared.connectors.ports`); this module owns
mailboxes and registers them itself. Whether a kind is in the tenant's edition is asked of the
entitlement interface only (CLAUDE.md rule 5f).

Reading the catalogue needs `integrations.view` (technicians by default). Setting up a kind needs
its category's permission (REQ-INT-013); without it the entry is read-only and says why, so the
console never guesses (AC1).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import Subject
from app.modules.integrations.domain.mailboxes import SECRET_FALLBACK, connector_status
from app.modules.integrations.infra.models import Mailbox
from app.modules.integrations.service.mailboxes import MANAGE as MAILBOXES_MANAGE
from app.modules.licensing import has_feature
from app.shared.connectors.ports import (
    ConnectorCategory,
    ConnectorInstance,
    ConnectorKind,
    ConnectorStatus,
    register_connector,
    registered_connectors,
)

VIEW = "integrations.view"
MAILBOX = "mailbox"


def manage_permission(category: ConnectorCategory) -> str:
    """The set-up permission of one category (REQ-INT-013).

    Mailboxes predate the catalogue: the email category keeps `mailboxes.manage` until the
    permission moves to `integrations.manage_email` by expand/contract (D-118).
    """
    if category == ConnectorCategory.EMAIL:
        return MAILBOXES_MANAGE
    return f"integrations.manage_{category.value}"


@dataclass(frozen=True)
class CatalogueEntry:
    """One kind as one person sees it."""

    kind: ConnectorKind
    available: bool  # in the tenant's edition
    can_manage: bool
    manage_reason: str | None  # why not: "not_in_edition" or "no_permission"
    instances: Sequence[ConnectorInstance]


async def catalogue(session: AsyncSession, subject: Subject) -> list[CatalogueEntry]:
    """Every registered kind with its instances, for `subject`."""
    entries: list[CatalogueEntry] = []
    for registered in registered_connectors():
        kind = registered.kind
        available = kind.feature is None or await has_feature(subject.tenant_id, kind.feature)
        allowed = subject.holds(manage_permission(kind.category))
        reason = (
            None
            if available and allowed
            else ("not_in_edition" if not available else "no_permission")
        )
        # A kind outside the edition has nothing to show; its old instances stay in its module.
        instances = await registered.source.instances(session) if available else ()
        entries.append(CatalogueEntry(kind, available, available and allowed, reason, instances))
    return entries


class MailboxConnectors:
    """Mailboxes as catalogue instances (WP-024's mail page stays their set-up)."""

    async def instances(self, session: AsyncSession) -> Sequence[ConnectorInstance]:
        """Every mailbox, by address."""
        rows = await session.scalars(
            select(Mailbox).where(Mailbox.deleted_at.is_(None)).order_by(Mailbox.address)
        )
        return [_mailbox(row) for row in rows]


def _mailbox(row: Mailbox) -> ConnectorInstance:
    fallback = row.secret_fallback_at is not None
    status = connector_status(row.state, enabled=row.enabled, secret_fallback=fallback)
    reason = {
        ConnectorStatus.FAILED: row.state_reason,
        ConnectorStatus.DEGRADED: SECRET_FALLBACK,
    }.get(status)
    working = status in {ConnectorStatus.ACTIVE, ConnectorStatus.DEGRADED}
    return ConnectorInstance(
        id=row.id,
        name=row.address,
        status=status,
        reason=reason,
        # The fetch stamps every attempt; only a working mailbox's last fetch was a success.
        # Connector runs (this session's next step) record successes on their own.
        last_success_at=row.last_fetch_at if working else None,
        next_run_at=row.next_fetch_at if row.enabled else None,
        credential_expires_at=row.credential_expires_at,
    )


MAILBOX_KIND = ConnectorKind(
    code=MAILBOX,
    category=ConnectorCategory.EMAIL,
    page="/admin/mail",
    reason_labels="mailbox_reason",
    keywords=("connector_keyword.imap", "connector_keyword.oauth", "connector_keyword.key"),
)


def register() -> None:
    """Put mailboxes in the catalogue (called when the module loads)."""
    register_connector(MAILBOX_KIND, MailboxConnectors())
