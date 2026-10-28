"""Words for report values written by the server (exports, emails; rule d, ADR-034).

The same rules as the console (apps/console/src/pages/reports/names.ts): built-in codes through
the shipped labels, admin values and records through the resolvers their modules register
(app/shared/reporting/names.py), people through identity_access, empty values as "Not set",
anything unknown as "Unknown value", never the raw code or id.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, tzinfo
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.domain.definition import AGE_BUCKETS, DateBucket
from app.modules.identity_access import user_contacts
from app.shared.labels import has_label, label
from app.shared.reporting import Dimension, DimensionKind, names_resolver


def field_label(name: str, language: str, custom_names: Mapping[str, str]) -> str:
    """A field's name as the console shows it."""
    if name.startswith("custom."):
        return custom_names.get(name) or label("reports.unknown_value", language)
    # The record's own field name where it has one, otherwise the report's (QA WP-035 BUG-01).
    for key in (f"work_item.field.{name}", f"report_field.{name}"):
        if has_label(key):
            return label(key, language)
    return label("reports.unknown_value", language)


def _bucket_text(bucket: DateBucket, value: Any, language: str) -> str:  # noqa: ANN401 - a database value
    if bucket == DateBucket.AGE:
        return label(f"age_bucket.{AGE_BUCKETS[int(value)][0]}", language)
    day = value.date() if isinstance(value, datetime) else value
    if not isinstance(day, date):
        return str(value)
    texts = {
        DateBucket.WEEK: lambda: label("reports.week_of", language, day=day.isoformat()),
        DateBucket.MONTH: lambda: f"{day.year:04d}-{day.month:02d}",
        DateBucket.QUARTER: lambda: label(
            "reports.quarter_of", language, quarter=(day.month - 1) // 3 + 1, year=day.year
        ),
        DateBucket.YEAR: lambda: f"{day.year:04d}",
    }
    text = texts.get(bucket)
    return text() if text else day.isoformat()


class Namer:
    """Names one grouping's values; resolves each kind once per export."""

    def __init__(
        self, session: AsyncSession, entity: str, language: str, zone: tzinfo = UTC
    ) -> None:
        self.session = session
        self.zone = zone
        self.entity = entity
        self.language = language
        self._cache: dict[tuple[str, str], dict[str, str]] = {}

    async def custom_field_names(self) -> Mapping[str, str]:
        """Names of the entity's custom fields ("custom.<key>"), in the reader's language."""
        resolver = names_resolver(f"{self.entity}.custom_field")
        return await resolver(self.session, (), self.language, "") if resolver else {}

    def _kind(self, field: str, dimension: Dimension) -> str | None:
        if dimension.kind == DimensionKind.REFERENCE:
            return dimension.reference
        if dimension.kind == DimensionKind.ADMIN_CODE:
            return (
                f"{self.entity}.custom" if field.startswith("custom.") else f"{self.entity}.{field}"
            )
        return None

    async def prepare(self, field: str, dimension: Dimension, values: Iterable[Any]) -> None:
        """Look up the names of these values (call before `name`)."""
        kind = self._kind(field, dimension)
        if kind is None:
            return
        wanted = sorted({str(v) for v in values if v is not None})
        if not wanted:
            return
        found: Mapping[str, str]
        if kind == "user":
            contacts = await user_contacts(self.session, wanted)
            found = {k: name for k, (name, _email) in contacts.items()}
        else:
            resolver = names_resolver(kind)
            found = await resolver(self.session, wanted, self.language, field) if resolver else {}
        self._cache.setdefault((kind, field), {}).update(found)

    def _plain(self, field: str, dimension: Dimension, value: object) -> str | None:
        """Values named without a lookup (codes, yes/no, numbers, dates)."""
        if dimension.kind == DimensionKind.CODE:
            key = f"{dimension.label_prefix or field}.{value}"
            return label(key, self.language) if has_label(key) else None
        if dimension.kind == DimensionKind.BOOLEAN:
            return label("filter.yes" if value is True else "filter.no", self.language)
        if dimension.kind == DimensionKind.NUMBER:
            return str(value)
        if dimension.kind == DimensionKind.DATETIME:
            return value.isoformat() if isinstance(value, datetime | date) else str(value)
        kind = self._kind(field, dimension) or ""
        return self._cache.get((kind, field), {}).get(str(value))

    def name(
        self, field: str, dimension: Dimension, value: object, bucket: DateBucket | None
    ) -> str:
        """The value as a reader sees it."""
        if value is None or value == "":
            return label("reports.not_set", self.language)
        if bucket is not None:
            return _bucket_text(bucket, value, self.language)
        return self._plain(field, dimension, value) or label("reports.unknown_value", self.language)


def measure_label(entity: str, code: str, language: str) -> str:
    """A measure's name."""
    return label(f"measure.{entity}.{code}", language)


def join_names(names: Sequence[str]) -> str:
    """Grouping values of one row joined for a single cell."""
    return " · ".join(names)
