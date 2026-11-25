"""Catalog item names for report files (WP-047b S1; REQ-CAT-021 AC2, the charge-back report).

Registered with the reporting port (app/shared/reporting/names.py) when this module is imported,
so the consumers worker, which never runs startup hooks, has them too. An item's name in the
reader's language, English when it has none there; never its ID (rule d).
"""

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.service_catalog.infra.models import CatalogItem
from app.shared.reporting import register_names

KIND = "catalog_item"


def _ids(values: Sequence[str]) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for value in values:
        try:
            out.append(uuid.UUID(value))
        except ValueError:
            continue
    return out


async def item_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """Item names in `language`, English as the fallback (retired and deleted items too)."""
    del field
    rows = await session.execute(
        select(CatalogItem.id, CatalogItem.names).where(CatalogItem.id.in_(_ids(values)))
    )
    found: dict[str, str] = {}
    for row in rows:
        names = dict(row.names or {})
        text = names.get(language) or names.get("en")
        if text:
            found[str(row.id)] = str(text)
    return found


def register() -> None:
    """Make catalog items nameable in report files (module import)."""
    register_names(KIND, item_names)


__all__ = ["KIND", "item_names", "register"]
