"""Who still uses a key (ADR-048): a hook so a key is never dropped while data needs it.

Modules whose data outlives a restart register `async (key_id) -> int` for a ring: how many of
their stored items need that key to open. Sessions register nothing: they expire on their own,
so the overlap (the absolute session lifetime) is enough. WP-057's field encryption will register
its count of data keys still wrapped under a key.

At start-up the ring's owner asks, for every key it saw before but no longer lists, whether any
user still counts items under it, and refuses to start when one does (`KeyStillInUseError`).
With nothing registered the check never refuses.
"""

from collections.abc import Awaitable, Callable, Iterable

KeyUserCount = Callable[[str], Awaitable[int]]

_USERS: dict[str, dict[str, KeyUserCount]] = {}


class KeyStillInUseError(RuntimeError):
    """A key that was removed from a ring is still needed: the process must not start."""

    def __init__(self, ring: str, key_id: str, user: str, count: int) -> None:
        # A stable code per ring, e.g. `session_key_still_in_use` (labelled in errors.*).
        self.code = f"{ring}_key_still_in_use"
        self.ring = ring
        self.key_id = key_id
        self.user = user
        self.count = count
        super().__init__(
            f"{self.code}: key {key_id!r} was removed from the {ring} key ring but {user} still "
            f"has {count} item(s) that need it; list the key again until they have moved to a "
            "newer key"
        )


def register_key_user(ring: str, name: str, count: KeyUserCount) -> None:
    """Register (or replace) `name`'s count of items under a key of `ring`."""
    _USERS.setdefault(ring, {})[name] = count


def unregister_key_user(ring: str, name: str) -> None:
    """Forget a registration (tests, module shutdown)."""
    _USERS.get(ring, {}).pop(name, None)


def key_users(ring: str) -> dict[str, KeyUserCount]:
    """The registered users of `ring`, by name."""
    return dict(_USERS.get(ring, {}))


async def refuse_if_still_used(ring: str, removed: Iterable[str]) -> None:
    """Raise KeyStillInUseError when a registered user still counts items under a removed key."""
    users = key_users(ring)
    for key_id in removed:
        for name, count in users.items():
            found = await count(key_id)
            if found > 0:
                raise KeyStillInUseError(ring, key_id, name, found)
