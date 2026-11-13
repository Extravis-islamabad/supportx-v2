"""What one asset save reads again and again, kept for the rest of its (sub)transaction (S4c).

An import or a copy saves many assets in one transaction, and each save reads the same tenant
configuration: the default in-stock state, the settings row, the product type tree, the
tenant's time zone. They are read once per transaction instead (WP-049b S4c).

The memo belongs to the innermost transaction open when it is read: a savepoint gets its own,
which ends with it. A savepoint that rolls back (a dry run, a refused row) can therefore never
leave behind a memo of something it wrote, such as the first defaults of a new tenant. Only
configuration is kept, and the products a save names (a batch names the same few on thousands
of rows; one retired meanwhile counts as live until the batch ends, about two seconds). The
site and the vendor of a save are still checked on every save. The other exception, the asset
limit's count in an import's batch savepoint, is `keep_slot_count`'s, with its reasons.

Unlike app/core/database.py's `transaction_memo`, which lives per session until the outermost
transaction ends or any savepoint rolls back, this memo is per (sub)transaction: a new
savepoint starts empty, even one that commits.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

_KEY = "supportx.assets.memo"


def memo(session: AsyncSession) -> dict[str, Any]:
    """The memo of the session's innermost open transaction (a fresh one for a new savepoint)."""
    sync = session.sync_session
    transaction = sync.get_nested_transaction() or sync.get_transaction()
    held = session.info.get(_KEY)
    if held is None or held[0] is not transaction:
        held = (transaction, {})
        session.info[_KEY] = held
    found: dict[str, Any] = held[1]
    return found


def keep_slot_count(session: AsyncSession) -> None:
    """In this savepoint, count the asset limit's slots once and add one per slot taken.

    For an import's batch savepoint only, where every save is `create_asset` / `update_asset`:
    the first count runs under the limit's lock, which the transaction then holds until it
    ends, so no other transaction adds a counted asset meanwhile and the count plus the slots
    taken here is never below the true one (a slot freed meanwhile only makes it higher). It
    can only refuse early, and a refusal makes the import redo the batch row by row, each row
    counting afresh: the outcome is the row path's. Without it the import counted every asset
    once per row, a cost that grew with the table.
    """
    memo(session)["keep_slot_count"] = True
