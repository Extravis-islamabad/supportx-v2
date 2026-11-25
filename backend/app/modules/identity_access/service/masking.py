"""People's contacts (and, when asked, names) withheld from a support request's answers.

WP-057 S4c-2, D-173, D-180: every vendor support session carries `mask_contacts` on its request
context (set by the BFF's session resolve, with its grant): e-mail and phone are always withheld.
Names are withheld only when the grant ticks "Mask names too" (`mask_names`, 0188). Every people
lookup reads it from the database session's own context, so a lookup cannot forget it, nothing
is cached across requests, and workers, mail and jobs (no such context) are never masked.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import PermissionDenied
from app.core.tenancy import TenantContext

PERSON_SEARCH_MASKED = "person_search_masked"


def contacts_masked(session: AsyncSession) -> bool:
    """Whether this session's request withholds people's e-mail addresses and phones.

    Every vendor support session (D-180). Read from the request's own context, so every people
    lookup honours it and workers, mail and jobs (no such context) never do.
    """
    context = session.info.get(SESSION_TENANT_KEY)
    return isinstance(context, TenantContext) and context.mask_contacts


def names_masked(session: AsyncSession) -> bool:
    """Whether this session's request withholds people's names too (D-180: the grant's tick)."""
    context = session.info.get(SESSION_TENANT_KEY)
    return isinstance(context, TenantContext) and context.mask_names


def shown_name(session: AsyncSession, display_name: str) -> str:
    """A person's name as this request may see it: "" when withheld (the console's stand-in).

    Names are withheld when the grant masks them; and while contacts are masked, a name that is
    an address (a first sign-in without a name claim stores the e-mail as the name) is withheld
    too, or the address would show as the name (lane B's #566 review).
    """
    if names_masked(session):
        return ""
    if contacts_masked(session) and "@" in display_name:
        return ""
    return display_name


def refuse_masked_person_search(session: AsyncSession) -> None:
    """A search by a person's name would tell who they are: refused while names are masked.

    With names shown (D-180's default), a support session searches names only (person_search).
    """
    if names_masked(session):
        raise PermissionDenied(code=PERSON_SEARCH_MASKED)
