"""Who holds an asset and how assets relate: the pure rules (WP-049a s4; REQ-AST-018, 026, 027).

No I/O. The lists match migration 0111's checks.
"""

from collections.abc import Mapping

HOLDER_KINDS = ("user", "department", "asset")
RELATIONSHIP_KINDS = ("connected_to", "depends_on", "runs_on", "backs_up")


def would_nest_in_itself(
    asset_id: str, new_parent_id: str, parents: Mapping[str, str | None]
) -> bool:
    """True when fitting `asset_id` to `new_parent_id` puts it inside itself (REQ-AST-018 AC3).

    `parents` maps asset ID -> its parent asset ID. Walking up from the new parent must never
    reach the asset; a broken chain (a loop already stored) also counts, so it is refused.
    """
    seen: set[str] = set()
    current: str | None = new_parent_id
    while current is not None:
        if current == asset_id or current in seen:
            return True
        seen.add(current)
        current = parents.get(current)
    return False
