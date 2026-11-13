"""No start while a removed key still wraps data keys (ADR-050 addendum; WP-057 S3b-1; lane B).

Every tenant data key (`tenant_data_keys`) is wrapped by one key-encryption key of the
installation ring (`SUPPORTX_FILES_KEYS`). An operator who drops a KEK from the ring before its
data keys were rewrapped onto the new one makes those tenants' files and encrypted fields
unreadable. So the API refuses to start, naming the missing key IDs and how many data keys each
still wraps, never a tenant or a key; `make keys-check` asks the same before a key is removed.

The count comes from `sx_kek_wraps()` (migration 0163, made by the owned definer helper): the only
way across tenants, and it returns nothing but (kek_id, count).
"""

from dataclasses import dataclass

from sqlalchemy import text

from app.core.config import Settings
from app.core.database import Database
from app.shared.files.keyring import KeyRing

_WRAPS = text("SELECT kek_id, wraps FROM sx_kek_wraps()")


@dataclass(frozen=True)
class RemovedKeysInUse(RuntimeError):
    """KEKs gone from the ring that still wrap data keys: {kek_id: data keys it wraps}."""

    missing: dict[str, int]

    def __str__(self) -> str:
        """The key IDs and counts (never a tenant), for the start-up log."""
        listed = ", ".join(f"{kek} wraps {count}" for kek, count in sorted(self.missing.items()))
        return (
            "key-encryption keys removed from SUPPORTX_FILES_KEYS still wrap data keys "
            f"({listed}): put them back, rewrap, then remove them"
        )


async def wraps(database: Database) -> dict[str, int]:
    """How many data keys each KEK wraps, over every tenant."""
    async with database.platform_session() as session:
        rows = (await session.execute(_WRAPS)).all()
    return {str(kek): int(count) for kek, count in rows}


async def missing_keys(database: Database, ring: KeyRing) -> dict[str, int]:
    """The KEKs not in `ring` that still wrap data keys, with how many each."""
    return {kek: count for kek, count in (await wraps(database)).items() if kek not in ring.keys}


async def check_key_wraps(database: Database, settings: Settings) -> None:
    """Refuse to start (RemovedKeysInUse) while a removed KEK still wraps data keys.

    No ring configured: nothing to compare (files and field encryption are off).
    """
    from app.shared.fields import field_keys  # noqa: PLC0415 - the package imports this module

    ring = field_keys(settings)
    if ring is None:
        return
    missing = await missing_keys(database, ring)
    if missing:
        raise RemovedKeysInUse(missing)
