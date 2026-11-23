"""Every built-in CMDB relationship type reads in both directions in every language (WP-053 S2).

A built-in type stores no names: the UI labels it `cmdb_relationship.<code>.forward` ("runs on")
and `.inverse` ("hosts"), so "A runs on B" shows on B as "B hosts A" (REQ-CMDB-006 AC1).
"""

import pytest

from app.modules.cmdb.domain.relationships import BUILT_IN_TYPES
from tests.test_error_labels import label_keys


@pytest.mark.parametrize("locale", ["en", "ar", "ur"])
def test_every_built_in_relationship_type_has_both_names(locale: str) -> None:
    keys = label_keys(locale)
    missing = [
        f"cmdb_relationship.{code}.{side}"
        for code, _ in BUILT_IN_TYPES
        for side in ("forward", "inverse")
        if f"cmdb_relationship.{code}.{side}" not in keys
    ]
    assert missing == []
