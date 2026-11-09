"""Signed one-time action links (WP-030 s3; REQ-NTF-024): see domain.py and service.py.

Public interface: `issue`, `peek`, `use`, `revoke_for`, `register_handler`, `ActionHandler`,
`Opened`, `LinkRefused`, `Refusal`.
"""

from app.shared.action_links.domain import LinkRequest, Refusal, marker, public_page
from app.shared.action_links.service import (
    ActionHandler,
    Actor,
    LinkRefused,
    Opened,
    issue,
    note_failed_use,
    peek,
    recipient_of,
    register_handler,
    revoke_for,
    use,
)

__all__ = [
    "ActionHandler",
    "Actor",
    "LinkRefused",
    "LinkRequest",
    "Opened",
    "Refusal",
    "issue",
    "marker",
    "note_failed_use",
    "peek",
    "public_page",
    "recipient_of",
    "register_handler",
    "revoke_for",
    "use",
]
