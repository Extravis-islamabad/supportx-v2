"""A key ring (ADR-048): keys newest first; the newest seals, any listed key opens.

The ring is nothing more than the codec's `lookup` plus "which key is newest". Where the keys
come from (settings, a KMS later) is the owner's business: the session ring is built from
SUPPORTX_SESSION_KEYS by the identity module.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.shared.crypto.codec import KeyMaterial, key_id_of, open_sealed, seal


@dataclass(frozen=True)
class KeyRing:
    """Ordered keys, newest first. Never empty; key IDs are unique."""

    keys: tuple[KeyMaterial, ...]

    def __post_init__(self) -> None:  # noqa: D105 - validation only
        if not self.keys:
            msg = "a key ring needs at least one key"
            raise ValueError(msg)
        ids = [key.id for key in self.keys]
        if len(set(ids)) != len(ids):
            msg = "key IDs in a ring must be unique"
            raise ValueError(msg)

    @classmethod
    def of(cls, keys: Sequence[KeyMaterial]) -> "KeyRing":
        """A ring of `keys`, newest first."""
        return cls(tuple(keys))

    @property
    def newest(self) -> KeyMaterial:
        """The key new data is sealed under."""
        return self.keys[0]

    @property
    def ids(self) -> tuple[str, ...]:
        """Every listed key ID, newest first."""
        return tuple(key.id for key in self.keys)

    def lookup(self, key_id: str) -> bytes | None:
        """The secret of a listed key, or None: what `open_sealed` asks for."""
        for key in self.keys:
            if key.id == key_id:
                return key.secret
        return None

    def seal(self, purpose: str, bound_to: Sequence[str], plaintext: bytes) -> bytes:
        """A v2 blob under the newest key."""
        return seal(self.newest, purpose, bound_to, plaintext)

    def open(self, purpose: str, bound_to: Sequence[str], blob: bytes) -> bytes | None:
        """The plaintext of a blob sealed under any listed key, else None."""
        return open_sealed(self.lookup, purpose, bound_to, blob)

    def is_current(self, blob: bytes) -> bool:
        """Whether a blob is sealed under the newest key (no need to re-seal it)."""
        return key_id_of(blob) == self.newest.id
