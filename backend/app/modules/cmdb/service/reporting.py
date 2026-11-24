"""CIs and their relationships as reporting sources (WP-053 S5a; REQ-CMDB-032; WP-035 port).

The report builder and dashboards read the CMDB through these, never its tables (lane C's
WP-053 condition 4 and the coordinator's S5 conditions):

- **Rows are the list's own query** (`cis.visible_rows`): role scope and ADR-053's fine-grained
  access sit inside it, so every count and group is made AFTER the reader's narrowing, and a
  report never includes a CI outside it (AC2).
- **Withheld fields** (ADR-047 hidden or masked, and sealed custom fields: `cis.withheld`) are
  out of both fields and dimensions and named in `withheld`, so a definition using one is
  refused as not permitted, never shown blank. Non-plain custom fields are never fields.
- **A relationship counts only when both of its CIs are visible**: a link to a CI the reader may
  not see is left out entirely, never a placeholder, so no count says a hidden CI exists or how
  it is linked (lane C, S5a review).
- `asset_id` is not reported: its value is another module's record, and a CMDB reader who may
  not see that asset would learn of it (lane C). People (`owner_user_id`) are the shared "user"
  reference the screens name themselves, with vendor support masking (D-180); the CMDB never
  names a person here.

The CMDB's own values (CI types, states, relationship types, CI custom choices) are named by
resolvers registered here, in the reader's language, for report files and e-mails (rule d).
Registered when the module is imported, like the assets source: the consumers worker runs
report exports without startup hooks.
"""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules import metadata
from app.modules.cmdb.infra.models import Ci, CiState, CiType, Relationship, RelationshipType
from app.modules.cmdb.service import cis
from app.modules.cmdb.service.catalogue import VIEW
from app.modules.identity_access import Subject
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.labels import label
from app.shared.reporting import (
    Dimension,
    DimensionKind,
    ReportingSource,
    register_names,
    register_source,
    unregister_names,
    unregister_source,
)

FEATURE = "cmdb"  # the module's licence feature (cmdb/__init__.py)
CI_ENTITY = "cmdb_ci"
RELATIONSHIP_ENTITY = "cmdb_relationship"
LIST_PATH = "cmdb"
NOT_REPORTED = frozenset({"asset_id", "id"})  # another module's record; the row's own key
_D = DimensionKind

CI_DIMENSIONS: Mapping[str, Dimension] = {
    "type_id": Dimension(_D.REFERENCE, reference="ci_type"),
    "state_id": Dimension(_D.REFERENCE, reference="ci_state"),
    "site_id": Dimension(_D.REFERENCE, reference="site"),
    "owner_user_id": Dimension(_D.REFERENCE, reference="user"),
    "owner_group_id": Dimension(_D.REFERENCE, reference="group"),
    "managed_by_group_id": Dimension(_D.REFERENCE, reference="group"),
    "business_impact": Dimension(_D.CODE, label_prefix="cmdb_impact"),
    "criticality": Dimension(_D.CODE, label_prefix="cmdb_impact"),
    "source": Dimension(_D.CODE, label_prefix="cmdb_ci_source"),
    "created_at": Dimension(_D.DATETIME),
    "updated_at": Dimension(_D.DATETIME),
}

_FROM = aliased(Ci)
_TO = aliased(Ci)
RELATIONSHIP_FIELDS = ResourceFields(
    name="cmdb_relationships",
    fields={
        "type_id": FilterField(Relationship.type_id, FieldType.UUID),
        "from_ci_id": FilterField(Relationship.from_ci_id, FieldType.UUID),
        "to_ci_id": FilterField(Relationship.to_ci_id, FieldType.UUID),
        "from_ci_type_id": FilterField(
            select(Ci.type_id).where(Ci.id == Relationship.from_ci_id).scalar_subquery(),
            FieldType.UUID,
        ),
        "to_ci_type_id": FilterField(
            select(Ci.type_id).where(Ci.id == Relationship.to_ci_id).scalar_subquery(),
            FieldType.UUID,
        ),
        "created_at": FilterField(Relationship.created_at, FieldType.DATETIME, simple=False),
    },
    id_column=Relationship.id,
    default_sort=("-created_at",),
)
# The CI IDs filter (drill-down from a CI) but never group: a group's key would be a CI's ID.
RELATIONSHIP_DIMENSIONS: Mapping[str, Dimension] = {
    "type_id": Dimension(_D.REFERENCE, reference="ci_relationship_type"),
    "from_ci_type_id": Dimension(_D.REFERENCE, reference="ci_type"),
    "to_ci_type_id": Dimension(_D.REFERENCE, reference="ci_type"),
    "created_at": Dimension(_D.DATETIME),
}


def _subject(subject: Any) -> Subject:  # noqa: ANN401 - the port is typed for shared code
    if not isinstance(subject, Subject):
        raise TypeError(subject)
    return subject


def ci_rows(subject: Subject) -> Select[Any]:
    """The CI source's rows: the list's own narrowed query (the guard proves its scope_filter)."""
    return cis.visible_rows(subject)


def relationship_rows(subject: Subject) -> Select[Any]:
    """Live relationships whose two CIs the reader may both see (both ends narrowed)."""
    visible = ci_rows(subject).with_only_columns(Ci.id).scalar_subquery()
    return select(Relationship).where(
        Relationship.deleted_at.is_(None),
        Relationship.from_ci_id.in_(visible),
        Relationship.to_ci_id.in_(visible),
    )


class CiSource:
    """The reporting provider of CIs."""

    @property
    def entity(self) -> str:
        """Entity code."""
        return CI_ENTITY

    @property
    def feature(self) -> str:
        """The CMDB licence feature."""
        return FEATURE

    @property
    def permission(self) -> str:
        """The list permission."""
        return VIEW

    async def source(self, session: AsyncSession, subject: Any) -> ReportingSource:  # noqa: ANN401 - Subject; the port is typed for shared code
        """CIs as `subject` may list them (narrowing included), minus what they may not read."""
        reader = _subject(subject)
        custom = await metadata.filter_fields(session, cis.ENTITY, "cmdb_cis")
        withheld = await cis.withheld(session, reader)
        dimensions = dict(CI_DIMENSIONS)
        for name, spec in custom.items():
            # Single choices group by their admin label; multi-choice is not groupable (as for
            # work items).
            if spec.type == FieldType.ENUM and not spec.array:
                dimensions[name] = Dimension(_D.ADMIN_CODE)
        fields = {
            name: field
            for name, field in {**cis.CI_FIELDS.fields, **custom}.items()
            if name not in withheld and name not in NOT_REPORTED
        }
        return ReportingSource(
            entity=CI_ENTITY,
            rows=ci_rows(reader),
            fields=ResourceFields(cis.CI_FIELDS.name, fields, cis.CI_FIELDS.id_column),
            dimensions={n: d for n, d in dimensions.items() if n in fields},
            list_path=LIST_PATH,
            withheld=withheld,
        )


class RelationshipSource:
    """The reporting provider of CI relationships (the CI relationships report)."""

    @property
    def entity(self) -> str:
        """Entity code."""
        return RELATIONSHIP_ENTITY

    @property
    def feature(self) -> str:
        """The CMDB licence feature."""
        return FEATURE

    @property
    def permission(self) -> str:
        """The list permission (CIs: a relationship is read through its CIs)."""
        return VIEW

    async def source(self, session: AsyncSession, subject: Any) -> ReportingSource:  # noqa: ANN401 - Subject; the port is typed for shared code
        """Live relationships whose two CIs the reader may both see; nothing else counts."""
        del session
        return ReportingSource(
            entity=RELATIONSHIP_ENTITY,
            rows=relationship_rows(_subject(subject)),
            fields=RELATIONSHIP_FIELDS,
            dimensions=RELATIONSHIP_DIMENSIONS,
            list_path=LIST_PATH,
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
    """A per-language name in the reader's language, else English."""
    if not names:
        return None
    return names.get(language) or names.get("en")


def _named(rows: Any, prefix: str, language: str) -> dict[str, str]:  # noqa: ANN401 - result rows
    """A built-in record by its label (`<prefix>.<api_name>`), a tenant's own by its names."""
    out: dict[str, str] = {}
    for r in rows:
        name = label(f"{prefix}.{r.api_name}", language) if r.built_in else _in(r.names, language)
        if name:
            out[str(r.id)] = name
    return out


async def type_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """CI type names in the reader's language (a built-in type by its label)."""
    del field
    rows = await session.execute(
        select(CiType.id, CiType.api_name, CiType.built_in, CiType.names).where(
            CiType.id.in_(_ids(values))
        )
    )
    return _named(rows, "cmdb_ci_type", language)


async def state_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """CI state names in the reader's language (a built-in state by its label)."""
    del field
    rows = await session.execute(
        select(CiState.id, CiState.api_name, CiState.built_in, CiState.names).where(
            CiState.id.in_(_ids(values))
        )
    )
    return _named(rows, "cmdb_ci_state", language)


async def relationship_type_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """A relationship type by its forward name (built-in ones from the labels)."""
    del field
    rows = await session.execute(
        select(
            RelationshipType.id,
            RelationshipType.code,
            RelationshipType.built_in,
            RelationshipType.names_forward,
        ).where(RelationshipType.id.in_(_ids(values)))
    )
    out: dict[str, str] = {}
    for r in rows:
        name = (
            label(f"cmdb_relationship.{r.code}.forward", language)
            if r.built_in
            else _in(r.names_forward, language)
        )
        if name:
            out[str(r.id)] = name
    return out


async def custom_choice_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """Choice labels of one CI custom field ("custom.<key>"); retired ones say so."""
    definition = (await metadata.definitions(session, cis.ENTITY)).get(
        field.removeprefix("custom.")
    )
    if definition is None:
        return {}
    wanted = set(values)
    out: dict[str, str] = {}
    for choice in definition.choices:
        if choice.code not in wanted:
            continue
        name = choice.labels.get(language) or choice.labels.get("en")
        if name:
            out[choice.code] = (
                label("custom_fields.retired_value", language, name=name)
                if choice.retired
                else name
            )
    return out


_RESOLVERS = {
    "ci_type": type_names,
    "ci_state": state_names,
    "ci_relationship_type": relationship_type_names,
    f"{CI_ENTITY}.custom": custom_choice_names,
}


def register() -> None:
    """Make CIs and relationships reportable and their values nameable (at import)."""
    register_source(CiSource())
    register_source(RelationshipSource())
    for kind, resolver in _RESOLVERS.items():
        register_names(kind, resolver)


def unregister() -> None:
    """Undo `register` (tests)."""
    unregister_source(CI_ENTITY)
    unregister_source(RELATIONSHIP_ENTITY)
    for kind in _RESOLVERS:
        unregister_names(kind)
