"""The work item reporting sources (WP-035 port, D-100 D9)."""

import subprocess
import sys

from app.modules.work_items.domain.types import TYPES
from app.modules.work_items.service.access import FIELDS
from app.modules.work_items.service.reporting import (
    DIMENSIONS,
    register_sources,
    unregister_sources,
)
from app.shared.reporting import DimensionKind, provider_for, registered_entities


def test_every_dimension_is_a_list_filter_field() -> None:
    assert set(DIMENSIONS) <= set(FIELDS.fields)


def test_code_dimensions_name_their_label_prefix() -> None:
    for dimension in DIMENSIONS.values():
        assert (dimension.kind == DimensionKind.CODE) == (dimension.label_prefix is not None)
        assert (dimension.kind == DimensionKind.REFERENCE) == (dimension.reference is not None)


def test_each_type_registers_with_its_list_permission_and_feature() -> None:
    register_sources()
    try:
        for wtype in TYPES.values():
            provider = provider_for(wtype.code.value)
            assert provider.permission == f"{wtype.permission_prefix}.view"
            assert provider.feature == wtype.feature
    finally:
        unregister_sources()
    assert not set(registered_entities()) & {w.code.value for w in TYPES.values()}
    register_sources()  # as at import: other tests and the workers rely on it


def test_sources_are_registered_at_import_for_the_workers() -> None:
    """The consumers worker imports modules without their startup hooks (report exports).

    A fresh process, as the worker starts: in this one, app shutdowns of other tests unregister.
    """
    probe = (
        "import app.modules.work_items\n"
        "from app.shared.reporting import registered_entities\n"
        "assert 'incident' in registered_entities(), registered_entities()\n"
    )
    done = subprocess.run(  # noqa: S603 - fixed argv: this interpreter and a literal script
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


def test_list_columns_are_fields_the_records_export_takes() -> None:
    """The console's built-in columns (pages/incidents/list/columns.tsx) are list fields, so the
    export (lane C's #108, which takes the entity's fields) gets the same columns."""
    columns = {
        "display_id",
        "subject",
        "requester_id",
        "status",
        "priority",
        "group_id",
        "technician_id",
        "resolution_due_at",
        "updated_at",
        "created_at",
        "status_changed_at",
        "first_responded_at",
        "resolved_at",
        "closed_at",
        "status_category",
        "channel",
        "impact",
        "urgency",
        "level",
        "closure_code",
        "site_id",
        "department_id",
        "category_id",
        "reopen_count",
    }
    assert columns <= set(FIELDS.fields)
