"""The work item reporting sources (WP-035 port, D-100 D9)."""

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
