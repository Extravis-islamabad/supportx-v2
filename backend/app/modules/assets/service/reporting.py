"""Assets as a reporting source (WP-035 port, ADR-033; lane C's P6 review).

The module hands analytics its own list query (`staff_rows`, scope filter included) and the
list's filter fields, so a report never counts an asset the viewer could not list. The values
it groups by that are this module's records (states, product types, products) are named by
resolvers registered here, in the reader's language, for report files and e-mails (rule d).
Registered when the module is imported: the consumers worker runs report exports without
startup hooks.
"""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assets.infra.models import AssetProduct, AssetProductType, AssetState
from app.modules.assets.service.assets import ASSET_FIELDS, VIEW, staff_rows
from app.modules.identity_access import Subject
from app.shared.reporting import (
    Dimension,
    DimensionKind,
    ReportingSource,
    register_names,
    register_source,
    unregister_names,
    unregister_source,
)

ENTITY = "asset"
FEATURE = "assets"  # the module's licence feature (assets/__init__.py)
_D = DimensionKind
DIMENSIONS: Mapping[str, Dimension] = {
    "state_id": Dimension(_D.REFERENCE, reference="asset_state"),
    "product_type_id": Dimension(_D.REFERENCE, reference="asset_product_type"),
    "product_id": Dimension(_D.REFERENCE, reference="asset_product"),
    "vendor_id": Dimension(_D.REFERENCE, reference="vendor"),
    "site_id": Dimension(_D.REFERENCE, reference="site"),
    "acquired_on": Dimension(_D.DATETIME),  # age, by bucket
    "warranty_expires_on": Dimension(_D.DATETIME),  # warranty ending
    "created_at": Dimension(_D.DATETIME),
}


class AssetSource:
    """The reporting provider of assets."""

    @property
    def entity(self) -> str:
        """Entity code."""
        return ENTITY

    @property
    def feature(self) -> str:
        """The assets licence feature."""
        return FEATURE

    @property
    def permission(self) -> str:
        """The list permission."""
        return VIEW

    async def source(self, session: AsyncSession, subject: Any) -> ReportingSource:  # noqa: ANN401 - Subject; the port is typed for shared code
        """Assets as `subject` may list them, with the list's filter fields."""
        del session
        if not isinstance(subject, Subject):
            raise TypeError(subject)
        return ReportingSource(
            entity=ENTITY,
            rows=staff_rows(subject),
            fields=ASSET_FIELDS,
            dimensions=DIMENSIONS,
            list_path="assets",
        )


def _ids(values: Sequence[str]) -> list[uuid.UUID]:
    found: list[uuid.UUID] = []
    for value in values:
        try:
            found.append(uuid.UUID(value))
        except ValueError:
            continue
    return found


def _in(names: Mapping[str, str] | None, language: str) -> str | None:
    """A per-language name in the reader's language, else English (always present)."""
    if not names:
        return None
    return names.get(language) or names.get("en")


async def state_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """Asset state names in the reader's language."""
    del field
    rows = await session.execute(
        select(AssetState.id, AssetState.names).where(AssetState.id.in_(_ids(values)))
    )
    return {str(r.id): name for r in rows if (name := _in(r.names, language))}


async def product_type_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """Product type names in the reader's language."""
    del field
    rows = await session.execute(
        select(AssetProductType.id, AssetProductType.names).where(
            AssetProductType.id.in_(_ids(values))
        )
    )
    return {str(r.id): name for r in rows if (name := _in(r.names, language))}


async def product_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """Product names (one name each, as the catalogue keeps them)."""
    del language, field
    rows = await session.execute(
        select(AssetProduct.id, AssetProduct.name).where(AssetProduct.id.in_(_ids(values)))
    )
    return {str(r.id): r.name for r in rows}


def register() -> None:
    """Make assets reportable and their values nameable (at import)."""
    register_source(AssetSource())
    register_names("asset_state", state_names)
    register_names("asset_product_type", product_type_names)
    register_names("asset_product", product_names)


def unregister() -> None:
    """Undo `register` (tests)."""
    unregister_source(ENTITY)
    for kind in ("asset_state", "asset_product_type", "asset_product"):
        unregister_names(kind)
