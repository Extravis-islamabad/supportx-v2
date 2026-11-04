"""An Entra directory's sync app, typed (WP-040 session 2).

`directory_connectors` also holds AD/LDAP directories (migration 0055), whose Entra columns are
empty; a database check keeps them filled for Entra. Entra code reads them through here.
"""

from dataclasses import dataclass

from app.core.errors import NotFound
from app.modules.integrations.domain.mailboxes import CredentialKind
from app.modules.integrations.infra.models import DirectoryConnector

ENTRA = "entra"


@dataclass(frozen=True)
class EntraApp:
    """The customer's least-privilege sync app (its secret is in the secrets store)."""

    directory_tenant: str
    client_id: str
    credential_kind: CredentialKind


def entra_app(row: DirectoryConnector) -> EntraApp:
    """The row's sync app; 404 for a directory that is not Entra's."""
    if (
        row.source != ENTRA
        or row.directory_tenant is None
        or row.client_id is None
        or row.credential_kind is None
    ):
        raise NotFound(code="directory_not_found")
    return EntraApp(row.directory_tenant, row.client_id, CredentialKind(row.credential_kind))
