"""Catalog search (WP-031 s1, plan D12; REQ-CAT-028; ADR-039).

The shared search port (ADR-029) over the item's own generated columns: names, keywords and
summaries (weight A) and descriptions (weight B) in every language, with the shared
normalisation (Arabic and Urdu letter variants and diacritics) and typo tolerance on names and
keywords. It starts from the very query that lists the viewer's items (`offered`), so search
never shows an item the viewer could not open. Best match first; ties go to featured items,
then the catalog order.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import Subject
from app.modules.service_catalog.infra.models import CatalogItem
from app.modules.service_catalog.service.catalog import MANAGE, ItemView, offered, rules_of
from app.shared.search import ENGINE, SearchDocument

_COLUMNS = CatalogItem.__table__.c
TEXT = SearchDocument(vector=_COLUMNS.search_vector, short_text=_COLUMNS.search_name)
MAX_RESULTS = 50


async def search_items(
    session: AsyncSession, subject: Subject, text: str, *, limit: int = 20
) -> list[ItemView]:
    """Items the viewer may see that match `text`, best first (none if it has no words)."""
    words = await ENGINE.match(session, TEXT, text)
    if words is None:
        return []
    query = (await offered(session, subject)).where(words.predicate)
    rows = await session.scalars(
        query.order_by(
            words.rank.desc(),
            CatalogItem.featured.desc(),
            CatalogItem.sort_order,
            CatalogItem.id,
        ).limit(max(1, min(limit, MAX_RESULTS)))
    )
    manage = subject.holds(MANAGE)
    return [ItemView(r, rules_of(r), manage) for r in rows]


__all__ = ["search_items"]
