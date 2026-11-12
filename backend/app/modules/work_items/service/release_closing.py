"""What is still open on a release when it closes (WP-058b S4; REQ-REL-052).

Two kinds of open work, generic in the shared closing check (closure.OpenWorkKind), reported
here for releases: the changes linked to it (`in_release`: change -> release) that are not
closed yet, and its open sub-releases (`sub_release_of`: sub -> parent). Both warn by default:
the user sees them named ("CHG-12 Core switch firmware") and confirms; the confirmation goes
into history with the items (the shared check). Any other type has none of either.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_items.domain.closure import OpenItem, OpenWorkKind
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.types import WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItem, WorkItemLink

_OPEN = (StatusCategory.OPEN.value, StatusCategory.PAUSED.value)


async def _open_sources(
    session: AsyncSession, record: WorkItem, kind: LinkKind, open_kind: OpenWorkKind
) -> list[OpenItem]:
    if record.type != WorkItemTypeCode.RELEASE.value:
        return []
    rows = await session.execute(
        select(WorkItem.display_id, WorkItem.subject)
        .join(
            WorkItemLink,
            (WorkItemLink.source_id == WorkItem.id)
            & (WorkItemLink.tenant_id == WorkItem.tenant_id),
        )
        .where(
            # The tenant as well as RLS (lane A's review of S3): never another tenant's records.
            WorkItemLink.tenant_id == record.tenant_id,
            WorkItemLink.target_id == record.id,
            WorkItemLink.kind == kind.value,
            WorkItem.deleted_at.is_(None),
            WorkItem.status_category.in_(_OPEN),
        )
        .order_by(WorkItem.display_id)
    )
    return [OpenItem(open_kind, f"{row.display_id} {row.subject}") for row in rows]


async def open_linked_changes(session: AsyncSession, record: WorkItem) -> list[OpenItem]:
    """The release's changes not closed yet (REQ-REL-052 AC1: named, confirmed)."""
    return await _open_sources(session, record, LinkKind.IN_RELEASE, OpenWorkKind.LINKED_CHANGES)


async def open_sub_releases(session: AsyncSession, record: WorkItem) -> list[OpenItem]:
    """The release's sub-releases not closed yet."""
    return await _open_sources(
        session, record, LinkKind.SUB_RELEASE_OF, OpenWorkKind.CHILD_RELEASES
    )
