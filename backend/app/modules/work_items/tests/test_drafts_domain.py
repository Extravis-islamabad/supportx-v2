"""Kept drafts' rules (WP-046a S5c; REQ-INC-019; lane B's conditions)."""

import json

import pytest

from app.modules.work_items.domain import drafts


def test_only_known_forms_keep_drafts() -> None:
    assert drafts.form_type("incident-new") == "incident"
    assert drafts.form_type("anything-else") is None


def test_plain_values_are_kept_as_json() -> None:
    values = {"subject": "Mail is down", "priority": "p2", "tags": ["vpn"], "custom": {"x": 1}}
    assert json.loads(drafts.checked(values)) == values


@pytest.mark.parametrize(
    "values",
    [
        ["not", "an", "object"],
        {"attachment_ids": ["a"]},  # nothing that names a file
        {"inline_files": []},
        {"nested": {"deeper": {"x": 1}}},
        {f"k{i}": i for i in range(drafts.MAX_KEYS + 1)},
    ],
)
def test_anything_but_plain_values_is_refused(values: object) -> None:
    with pytest.raises(drafts.DraftRefused) as refused:
        drafts.checked(values)
    assert refused.value.code == "draft_not_values"


def test_too_large_is_refused_before_sealing() -> None:
    with pytest.raises(drafts.DraftRefused) as refused:
        drafts.checked({"description": "x" * (drafts.BODY_MAX + 1)})
    assert refused.value.code == "draft_too_large"
