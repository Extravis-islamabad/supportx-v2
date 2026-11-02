"""What the connector catalogue asks of the modules that own connectors (WP-040, REQ-INT-001).

One catalogue lists every integration, but the connectors live in different modules: mailboxes
and directory sync in `integrations`, MonetX in `monitoring_integrations`, AI providers in `ai`.
Each owner registers a `ConnectorKind` at startup and answers for its instances through a
`ConnectorSource`; the catalogue (integrations module) never reads their tables (architecture.md
§6.1). Shared code cannot import modules, so the contract lives here.

Statuses and categories are stable codes; the console shows their labels
(`connector_status.<code>`, `connector_category.<code>`, `connector_kind.<code>`).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class ConnectorCategory(StrEnum):
    """Catalogue groups (REQ-INT-001); set-up rights are given per category (REQ-INT-013)."""

    IDENTITY = "identity"
    EMAIL = "email"
    COLLABORATION = "collaboration"
    MONITORING = "monitoring"
    DEVOPS = "devops"
    ENDPOINT = "endpoint"
    TELEPHONY = "telephony"
    AUTOMATION = "automation"
    ANALYTICS = "analytics"
    KNOWLEDGE = "knowledge"
    AI = "ai"


class ConnectorStatus(StrEnum):
    """One instance's status as the catalogue shows it (REQ-INT-001)."""

    NOT_SET_UP = "not_set_up"
    ACTIVE = "active"
    DEGRADED = "degraded"
    FAILED = "failed"
    PAUSED = "paused"


class SecretType(StrEnum):
    """What kind of credential the secrets store holds (REQ-INT-003)."""

    PASSWORD = "password"  # noqa: S105 - a type code
    CLIENT_SECRET = "client_secret"  # noqa: S105 - a type code
    CERTIFICATE = "certificate"
    REFRESH_TOKEN = "refresh_token"  # noqa: S105 - a type code


@dataclass(frozen=True)
class ConnectorInstance:
    """One configured connector (a mailbox, a directory). Codes and times only, never secrets."""

    id: uuid.UUID
    name: str  # what the admin called it (an address, a directory name): user data, not a code
    status: ConnectorStatus
    reason: str | None = None  # a label code when failing or degraded
    last_success_at: datetime | None = None
    next_run_at: datetime | None = None
    credential_expires_at: datetime | None = None


@dataclass(frozen=True)
class ConnectorKind:
    """One kind of connector in the catalogue.

    `feature` is the licence feature that includes it (None: every edition); the catalogue asks
    the entitlement interface, never the deployment mode (CLAUDE.md rule 5f). `keywords` are
    label codes the console searches besides the name ("key", "API", "webhook"). `page` is the
    console route of its set-up. `multiple` says whether a tenant can add more than one.
    `reason_labels` is the label prefix of its instances' failure reasons (`mailbox_reason`).
    """

    code: str
    category: ConnectorCategory
    page: str
    reason_labels: str
    feature: str | None = None
    keywords: tuple[str, ...] = ()
    multiple: bool = True


class ConnectorSource(Protocol):
    """The owner module's answer for its instances, in the caller's tenant session."""

    async def instances(self, session: AsyncSession) -> Sequence[ConnectorInstance]:
        """Every instance of this kind in the tenant (removed ones left out)."""
        ...


@dataclass(frozen=True)
class Registered:
    """A kind and who answers for it."""

    kind: ConnectorKind
    source: ConnectorSource


_KINDS: dict[str, Registered] = {}


def register_connector(kind: ConnectorKind, source: ConnectorSource) -> None:
    """Called by the owner module at startup; a second registration replaces the first."""
    _KINDS[kind.code] = Registered(kind, source)


def unregister_connector(code: str) -> None:
    """Called at shutdown (and by tests)."""
    _KINDS.pop(code, None)


def registered_connectors() -> list[Registered]:
    """Every registered kind, in a stable order (category, then code)."""
    return sorted(_KINDS.values(), key=lambda r: (r.kind.category.value, r.kind.code))
