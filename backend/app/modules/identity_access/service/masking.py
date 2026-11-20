"""People's names and contacts withheld from a masked request's answers (WP-057 S4c-2, D-173).

A vendor support session whose grant does not unmask personal data carries `mask_contacts` on
its request context (set by the BFF's session resolve, with its grant). Every people lookup reads
it from the database session's own context, so a lookup cannot forget it, nothing is cached
across requests, and workers, mail and jobs (no such context) are never masked.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import PermissionDenied
from app.core.tenancy import TenantContext

PERSON_SEARCH_MASKED = "person_search_masked"


def contacts_masked(session: AsyncSession) -> bool:
    """Whether this session's request withholds people's names and contacts (D-173, S4c-2).

    Read from the request's own context (a vendor support session without unmask_personal), so
    every people lookup below honours it and workers, mail and jobs (no such context) never do.
    """
    context = session.info.get(SESSION_TENANT_KEY)
    return isinstance(context, TenantContext) and context.mask_contacts


def refuse_masked_person_search(session: AsyncSession) -> None:
    """A search by a person's name or e-mail would tell who they are: refused while masked."""
    if contacts_masked(session):
        raise PermissionDenied(code=PERSON_SEARCH_MASKED)
