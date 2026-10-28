"""Integrations module (architecture.md §6.1): connections to systems outside SupportX.

WP-024 starts it with support mailboxes: reading mail over IMAP (Microsoft Graph and the Gmail
API in session 2), turning it into incidents and replies, and the mail page. Outgoing mail stays
in the one sender, `app.shared.mail` (D-089).

Public interface for other modules: none yet.
"""

from app.core.modules import ModuleSpec
from app.modules.integrations.infra import models  # noqa: F401 - tables known to Alembic

module = ModuleSpec(name="integrations")

__all__ = ["module"]
