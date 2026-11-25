"""The merge and import rules (WP-053 S4b), without I/O."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.cmdb.domain import merge as domain

EARLY = datetime(2026, 1, 1, tzinfo=UTC)
LATE = EARLY + timedelta(days=30)


def _ids(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


def test_the_suggested_survivor_is_the_asset_linked_one_then_the_older() -> None:
    linked = domain.Candidate(asset_linked=True, created_at=LATE)
    plain = domain.Candidate(asset_linked=False, created_at=EARLY)
    assert domain.suggest_survivor(linked, plain) == 0
    assert domain.suggest_survivor(plain, linked) == 1
    older = domain.Candidate(asset_linked=False, created_at=EARLY)
    newer = domain.Candidate(asset_linked=False, created_at=LATE)
    assert domain.suggest_survivor(newer, older) == 1
    assert domain.suggest_survivor(older, older) == 0  # a tie keeps the order asked


@pytest.mark.parametrize(
    ("survivor", "merged", "side"),
    [
        ("A", "B", domain.CiMergeSide.SURVIVOR),
        (None, "B", domain.CiMergeSide.MERGED),
        ("  ", "B", domain.CiMergeSide.MERGED),
        (None, None, domain.CiMergeSide.SURVIVOR),
        ("A", None, domain.CiMergeSide.SURVIVOR),
    ],
)
def test_the_default_side_is_the_survivors_unless_it_has_no_value(
    survivor: object, merged: object, side: domain.CiMergeSide
) -> None:
    assert domain.default_side(survivor, merged) is side


def test_a_withheld_custom_field_is_never_offered_nor_chosen() -> None:
    """Lane C (9): hidden and masked fields are neither listed nor accepted as a choice."""
    fields = domain.mergeable_fields({"rack": "1", "key": "x"}, {"key": "y", "note": "n"}, {"key"})
    assert "custom.key" not in fields
    assert {"custom.rack", "custom.note", "name"} <= set(fields)
    problems = domain.choice_problems({"custom.key": "merged", "name": "sideways"}, fields)
    assert problems == [("choices.custom.key", "unknown_field"), ("choices.name", "invalid_choice")]


def test_links_move_to_the_survivor_and_duplicates_or_self_links_collapse() -> None:
    """AC1: two links to one service end as one; a link between the two CIs disappears."""
    survivor, merged, service, db = _ids(4)
    depends = uuid.uuid4()
    survivors_link = domain.Link(uuid.uuid4(), depends, survivor, service)
    to_service = domain.Link(uuid.uuid4(), depends, merged, service)
    to_db = domain.Link(uuid.uuid4(), depends, merged, db)
    between = domain.Link(uuid.uuid4(), depends, merged, survivor)
    moves = {
        m.link.id: m
        for m in domain.move_links([to_service, to_db, between], merged, survivor, [survivors_link])
    }
    assert moves[to_service.id].collapse
    assert moves[between.id].collapse
    kept = moves[to_db.id]
    assert not kept.collapse
    assert (kept.from_ci_id, kept.to_ci_id) == (survivor, db)


def test_two_of_the_merged_cis_links_that_meet_on_the_survivor_keep_one() -> None:
    survivor, merged, other = _ids(3)
    kind = uuid.uuid4()
    first = domain.Link(uuid.uuid4(), kind, merged, other)
    second = domain.Link(uuid.uuid4(), kind, survivor, merged)  # survivor -> merged: a self-link
    moves = domain.move_links([first, second], merged, survivor, [])
    assert [m.collapse for m in sorted(moves, key=lambda m: m.link.id == second.id)] == [
        False,
        True,
    ]


def test_an_import_header_must_name_known_columns_and_the_match_column() -> None:
    cis, by_name = domain.CiImportKind.CIS, domain.CiImportMatch.NAME
    assert domain.header_fields(cis, by_name, ["Name", "Business_Impact", ""]) == [
        "name",
        "business_impact",
        None,
    ]
    for cells, code in (
        (["Name", "Owner email"], "cmdb_import_unknown_column"),
        (["Name", "name"], "cmdb_import_duplicate_column"),
        (["Description"], "cmdb_import_missing_column"),
    ):
        with pytest.raises(domain.ImportRefused) as refused:
            domain.header_fields(cis, by_name, cells)
        assert refused.value.code == code
    with pytest.raises(domain.ImportRefused):
        domain.header_fields(domain.CiImportKind.RELATIONSHIPS, by_name, ["From", "To"])


def test_an_import_file_over_d092s_limits_is_refused_whole() -> None:
    """The coordinator's (4): the sheets' limits (columns here; zip and size alike)."""
    wide = (",".join(f"c{n}" for n in range(60)) + "\n").encode()
    with pytest.raises(domain.ImportRefused) as refused:
        domain.read_import(domain.CiImportKind.CIS, domain.CiImportMatch.NAME, "csv", wide)
    assert refused.value.code == "cmdb_import_too_many_columns"
    with pytest.raises(domain.ImportRefused) as refused:
        domain.read_import(
            domain.CiImportKind.CIS, domain.CiImportMatch.NAME, "xlsx", b"PK\x03\x04no"
        )
    assert refused.value.code.startswith("cmdb_import_file_")


@pytest.mark.parametrize("start", ["=", "+", "-", "@", "\t", "\r"])
def test_a_cell_that_would_open_as_a_formula_is_neutralised(start: str) -> None:
    assert domain.safe_cell(f"{start}SUM(A1)").startswith("'")
    assert domain.safe_cell("Plain text") == "Plain text"
