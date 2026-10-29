"""Event contracts published by the knowledge module (WP-033; docs/architecture/events.md).

Payloads carry IDs, codes and changed field names only, never titles or text (rule c): a
listener that needs words reads them through the module with its own reader's rights.
Session 2 adds the workflow event: submitted, approved, rejected, withdrawn and more (D-108 (5)).
"""

import uuid
from typing import ClassVar

from app.shared.events import DomainEvent


class KbTopicSaved(DomainEvent):
    """A topic was created or changed (moved, renamed, its audience)."""

    event_type: ClassVar[str] = "knowledge.topic.saved"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "kb_topic"

    topic_id: uuid.UUID
    created: bool
    changed_fields: list[str]


class KbTopicDeleted(DomainEvent):
    """A topic went to the trash; its articles moved to `moved_to` (REQ-KB-004 AC2)."""

    event_type: ClassVar[str] = "knowledge.topic.deleted"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "kb_topic"

    topic_id: uuid.UUID
    moved_to: uuid.UUID | None


class KbArticleSaved(DomainEvent):
    """An article or one of its drafts was created or changed (`language`: the draft's)."""

    event_type: ClassVar[str] = "knowledge.article.saved"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "kb_article"

    article_id: uuid.UUID
    topic_id: uuid.UUID
    owner_id: uuid.UUID
    language: str | None
    created: bool
    changed_fields: list[str]


class KbArticleWorkflow(DomainEvent):
    """A step of an article's review life (D-108 (5)), for notifications and live screens.

    Steps: submitted, approved, rejected, withdrawn, reviewed ("still correct"), deleted, restored.
    """

    event_type: ClassVar[str] = "knowledge.article.workflow"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "kb_article"

    article_id: uuid.UUID
    topic_id: uuid.UUID
    owner_id: uuid.UUID
    step: str  # WorkflowStep
    language: str | None
    version_number: int | None
    author_id: uuid.UUID | None  # who wrote the version (submitted / decided ones)
    # Whether the change touched what readers see (approve, withdraw, delete, restore): the
    # requester-facing broadcast is sent only then.
    readers_affected: bool


EVENTS: tuple[type[DomainEvent], ...] = (
    KbTopicSaved,
    KbTopicDeleted,
    KbArticleSaved,
    KbArticleWorkflow,
)
