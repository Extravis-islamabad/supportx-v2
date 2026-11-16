"""The key provider: the only thing that touches the installation key (ADR-050, D-161).

A Protocol only: crypto stays a leaf (the codec and this shape, nothing of files or fields).
Today's provider is the installation ring, `SUPPORTX_FILES_KEYS` (app/shared/files/keyring.py),
which already has this shape: a Kubernetes Secret on-prem and air-gapped, a KMS synced by External
Secrets Operator on SaaS, the same setting everywhere (no deployment-mode branch, rule 5f). A
customer's own KMS or HSM is another class with these three members, chosen by configuration
(D-161 item 3; not built).
"""

import uuid
from typing import Protocol


class KeyProvider(Protocol):
    """Wraps and unwraps tenant data keys under the installation key (ADR-050 item 1)."""

    @property
    def active_id(self) -> str:
        """The installation key new data keys are wrapped under."""
        ...

    def wrap(self, tenant_id: uuid.UUID, data_key: bytes) -> tuple[str, bytes]:
        """(installation key ID, wrapped bytes) of a tenant data key, bound to the tenant."""
        ...

    def unwrap(self, tenant_id: uuid.UUID, key_id: str, wrapped: bytes) -> bytes:
        """The tenant data key; raises when the installation key is missing or the bytes changed."""
        ...
