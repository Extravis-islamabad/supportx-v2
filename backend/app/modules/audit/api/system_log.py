"""The system log's routes (WP-057 S5b, REQ-AUD-016): read and export; nothing changes an entry.

- `GET /audit/system-log`: a page, newest first, filtered (`audit.view`). The read is logged
  (the audit log's read category, at most once per window).
- `GET /audit/system-log/export`: the same rows as the screen's filters, as CSV in the reader's
  language (`audit.export`; AC3). The export is audited.

There is no write route: entries come from modules through `record_system` (AC2).
"""

import csv
import io
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from app.core.database import TenantSession
from app.core.errors import BadRequest
from app.modules.audit.api.routes import Export, View
from app.modules.audit.domain.catalogue import ReadCategory
from app.modules.audit.domain.system_log import SystemLogCode, SystemLogSeverity
from app.modules.audit.infra.models import SystemLogEntry
from app.modules.audit.service import system_log
from app.modules.audit.service.recording import AuditNote, audit_read, audited
from app.shared.api.ratelimit import rate_limit
from app.shared.labels import label

router = APIRouter(
    prefix="/audit/system-log",
    tags=["audit"],
    dependencies=[Depends(rate_limit("audit"))],
)

Language = Literal["en", "ar", "ur"]


class SystemLogEntryOut(BaseModel):
    """One entry. The screen renders `code` with `params` through its label (never raw)."""

    id: uuid.UUID
    occurred_at: datetime
    severity: SystemLogSeverity
    module: str = Field(description="Labels: `system_log_module.<module>`.")
    code: SystemLogCode
    params: dict[str, str | int | float | bool | None]
    object_type: str | None = Field(description="What it's about; the screen links to it.")
    object_id: uuid.UUID | None
    job_id: str | None
    request_id: str | None


class SystemLogPage(BaseModel):
    """A page, newest first."""

    items: list[SystemLogEntryOut]
    next_after: str | None = Field(description="Pass as `after` for the next page.")


class _Filters:
    """The query string both routes share (AC3: the export is the screen's rows)."""

    def __init__(  # noqa: PLR0913, PLR0917 - one query parameter each (FastAPI)
        self,
        severity: Annotated[list[SystemLogSeverity] | None, Query()] = None,
        module: Annotated[list[str] | None, Query(max_length=64)] = None,
        code: Annotated[list[SystemLogCode] | None, Query()] = None,
        object_type: Annotated[str | None, Query(max_length=64)] = None,
        object_id: Annotated[uuid.UUID | None, Query()] = None,
        since: Annotated[datetime | None, Query()] = None,
        until: Annotated[datetime | None, Query()] = None,
    ) -> None:
        self.where = system_log.SystemLogFilter(
            severities=tuple(severity or ()),
            modules=tuple(module or ()),
            codes=tuple(code or ()),
            object_type=object_type,
            object_id=object_id,
            since=since,
            until=until,
        )


Filters = Annotated[_Filters, Depends()]


def _out(row: SystemLogEntry) -> SystemLogEntryOut:
    return SystemLogEntryOut.model_validate(row, from_attributes=True)


def _cursor(row: SystemLogEntry) -> str:
    return f"{row.occurred_at.isoformat()}|{row.id}"


def _after(value: str | None) -> tuple[datetime, uuid.UUID] | None:
    if value is None:
        return None
    try:
        at, _, last = value.partition("|")
        return datetime.fromisoformat(at), uuid.UUID(last)
    except ValueError:
        raise BadRequest(code="invalid_cursor") from None  # the shared cursor refusal


@router.get(
    "",
    summary="The system log",
    dependencies=[audit_read(ReadCategory.AUDIT_LOG)],
)
async def list_system_log(
    session: TenantSession,
    subject: View,
    filters: Filters,
    after: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=system_log.PAGE_MAX)] = system_log.PAGE,
) -> SystemLogPage:
    """Newest first; filter by severity, module, code, object and time (REQ-AUD-016 AC1)."""
    del subject
    rows = await system_log.entries(session, filters.where, after=_after(after), limit=limit + 1)
    more = len(rows) > limit
    rows = rows[:limit]
    return SystemLogPage(
        items=[_out(r) for r in rows],
        next_after=_cursor(rows[-1]) if more and rows else None,
    )


_HEADER = ("occurred_at", "severity", "module", "message", "object_type", "object_id", "job_id")


def _csv(rows: list[SystemLogEntry], language: str) -> str:
    """Each code in words, as the screen shows it; a leading formula character is neutralised."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([label(f"audit.system_log.column.{name}", language) for name in _HEADER])
    for row in rows:
        values = [
            row.occurred_at.isoformat(),
            label(f"system_log_severity.{row.severity}", language),
            label(f"system_log_module.{row.module}", language),
            label(f"system_log_code.{row.code}", language, **row.params),
            label(f"system_log_object.{row.object_type}", language) if row.object_type else "",
            str(row.object_id or ""),
            row.job_id or "",
        ]
        # CSV injection: a cell a spreadsheet would read as a formula starts with a quote.
        writer.writerow([f"'{v}" if v[:1] in {"=", "+", "-", "@"} else v for v in values])
    return buffer.getvalue()


@router.get(
    "/export",
    summary="Export the system log (CSV)",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def export_system_log(
    session: TenantSession,
    subject: Export,
    filters: Filters,
    note: Annotated[AuditNote, audited("audit.system_log_exported")],
    language: Annotated[Language, Query()] = "en",
) -> Response:
    """The screen's rows for the same filters, in `language` (REQ-AUD-016 AC3). Audited."""
    del subject
    rows = list(await system_log.export_rows(session, filters.where))
    note.details = {"rows": len(rows), "capped": len(rows) >= system_log.EXPORT_MAX}
    return Response(
        content="﻿" + _csv(rows, language),  # a BOM, so spreadsheets read UTF-8 (Arabic)
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="supportx-system-log.csv"'},
    )
