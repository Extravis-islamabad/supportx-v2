"""A request's snapshotted approval stages (WP-047a S2a; the coordinator's snapshot conditions)."""

import uuid

import pytest

from app.modules.work_items.domain.stage_snapshot import (
    VERSION,
    SnapApprover,
    SnapshotShapeError,
    SnapStage,
    from_json,
    person_ids,
    problems,
    to_json,
    without_person,
)

ANN = uuid.UUID("01900000-0000-7000-8000-0000000000a1")
BOB = uuid.UUID("01900000-0000-7000-8000-0000000000a2")
GROUP = uuid.UUID("01900000-0000-7000-8000-0000000000b1")

STAGES = (
    SnapStage((SnapApprover("requested_for_manager"),), backup_id=BOB),
    SnapStage(
        (SnapApprover("group", group_id=GROUP), SnapApprover("person", person_id=ANN)),
        rule="majority",
        parallel_group="finance",
        condition={"field": "quantity", "op": "ne", "value": 1},
        comments_required=True,
    ),
)


def test_it_round_trips_with_its_version_key_and_only_configuration() -> None:
    """Conditions 1 and 3: codes, IDs and switches under `v`; no name or e-mail anywhere."""
    stored = to_json(STAGES)
    assert stored["v"] == VERSION
    assert problems(stored) == []
    assert from_json(stored) == STAGES
    assert stored["stages"][0] == {
        "approvers": [{"kind": "requested_for_manager"}],
        "rule": "any",
        "backup_id": str(BOB),
        "comments_required": False,
        "self_approval": False,
    }
    text = str(stored)
    assert "@" not in text
    assert "name" not in text


@pytest.mark.parametrize(
    ("raw", "found"),
    [
        (None, ["not_an_object"]),
        ({"stages": []}, ["unknown_version"]),
        ({"v": 2, "stages": []}, ["unknown_version"]),
        ({"v": 1, "stages": {}}, ["bad_shape"]),
        ({"v": 1, "stages": [], "extra": 1}, ["bad_shape"]),
        ({"v": 1, "stages": [{"approvers": [{"kind": "anyone"}]}]}, ["stages.0.approvers.0"]),
        (
            {"v": 1, "stages": [{"approvers": [{"kind": "person", "email": "a@b.c"}]}]},
            ["stages.0.approvers.0"],
        ),
        ({"v": 1, "stages": [{"approvers": [], "rule": "loudest"}]}, ["stages.0"]),
        ({"v": 1, "stages": [{"approvers": [], "backup_id": "not-an-id"}]}, ["stages.0"]),
        ({"v": 1, "stages": [{"approvers": [], "names": {"en": "x"}}]}, ["stages.0"]),
        (
            {"v": 1, "stages": [{"approvers": [], "self_approval": "yes"}]},
            ["stages.0.self_approval"],
        ),
    ],
)
def test_a_stored_value_of_another_shape_is_refused_not_guessed(
    raw: object, found: list[str]
) -> None:
    assert problems(raw) == found
    with pytest.raises(SnapshotShapeError):
        from_json(raw)


def test_the_erasure_port_sees_and_removes_every_person_it_names() -> None:
    """Condition 2: named approvers and backups; a stage left empty falls back when it opens."""
    assert person_ids(STAGES) == {ANN, BOB}
    cleared = without_person(without_person(STAGES, ANN), BOB)
    assert person_ids(cleared) == set()
    assert cleared[0].backup_id is None
    assert cleared[1].approvers == (SnapApprover("group", group_id=GROUP),)
    assert cleared[1].rule == "majority"
