"""How a person is searched by text, for everyone (WP-057 S4c-3, D-180).

Lane B's and the coordinator's conditions: the one place that decides, so no search path keeps
an e-mail match by accident:

- staff: name and e-mail words, word forms in Arabic and Urdu, and typos (WP-027);
- a vendor support session (its contacts are always masked): the display name only, matched in
  the query itself, never the e-mail, username, phone or employee number, so typing part of an
  address ("ahmed@acme", "acme.com") finds nobody;
- a support session whose grant masks names too (0188): refused, 403 `person_search_masked`.
"""

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access.infra.models import User
from app.modules.identity_access.service.masking import (
    contacts_masked,
    names_masked,
    refuse_masked_person_search,
)
from app.shared.search import ENGINE, Match, SearchDocument

# Where people's searchable text lives (migration 0020): name and email words, and the name's
# trigrams for typos. Every staff people search uses it: the directory, pickers, assignees.
PEOPLE = SearchDocument(
    vector=User.__table__.c.search_vector, short_text=User.__table__.c.search_name
)


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def person_match(session: AsyncSession, text: str) -> Match | None:
    """The predicate and rank for a person search by `text`; None when nothing is searchable.

    Raises 403 `person_search_masked` when the request withholds names.
    """
    if names_masked(session):
        refuse_masked_person_search(session)
    if contacts_masked(session):
        typed = " ".join(text.split())
        if not typed:
            return None
        return Match(
            predicate=User.display_name.ilike(_like(typed), escape="\\"),
            rank=func.similarity(User.display_name, typed),
        )
    return await ENGINE.match(session, PEOPLE, text)
