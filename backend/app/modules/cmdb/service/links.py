"""The port that moves work items' CI links on a merge (WP-053 S4b; lane A's contract, 11-21).

Work items registers it with their `work_item_cis` (lane A, WP-053 S5). Until then nothing is
registered and a merge moves no work-item link (the count is 0; a test pins the call).

Lane A's contract, mirroring assets' `repoint_asset_links`, with one difference:
- `(session, from_ci_id, to_ci_id, *, source="system") -> int`, the records touched;
- a no-op when from == to; in the caller's transaction;
- a record already linking the target keeps one link;
- each moved record gets a history line, and the link removed/added events go out (live);
- no permission checks of its own: the CMDB checks before calling, and audits the merge;
- **no labels**: the history line stores the two CI IDs only, names resolved when read through
  the CMDB's visibility, so a restricted CI's name never lands in a work item's history.
"""

import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class CiLinksPort(Protocol):
    """Re-points every work item linked to one CI at another."""

    async def __call__(
        self,
        session: AsyncSession,
        from_ci_id: uuid.UUID,
        to_ci_id: uuid.UUID,
        *,
        source: str = "system",
    ) -> int:
        """The records touched (lane A's contract above)."""
        ...


_PORT: list[CiLinksPort] = []


def register_ci_links(port: CiLinksPort) -> None:
    """Work items' implementation (one; registering again replaces it)."""
    _PORT[:] = [port]


def ci_links_port() -> CiLinksPort | None:
    """The registered port, or None before work items registers one."""
    return _PORT[0] if _PORT else None


def clear_ci_links() -> None:
    """Tests only: back to no port."""
    _PORT.clear()
