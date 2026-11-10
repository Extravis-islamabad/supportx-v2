"""Which board reviews a change, the pure rules (WP-045b S2; REQ-CHG-041)."""

from app.modules.work_items.domain.change_boards import (
    BoardFacts,
    ChangeFacts,
    choose,
    mapping_problems,
    matches,
)


def _board(
    board_id: str,
    code: str | None,
    position: int,
    mapping: dict[str, list[str]] | None,
    *,
    default: bool = False,
    members: bool = True,
) -> BoardFacts:
    return BoardFacts(board_id, code, position, default, mapping, members)


DEFAULT = _board("b-cab", "cab", 0, None, default=True, members=False)
EMERGENCY = _board("b-ecab", "emergency_cab", 1, {"change_types": ["emergency"]})
PAYROLL = _board("b-pay", None, 2, {"risk_levels": ["high", "very_high"], "site_ids": ["s-hq"]})
HIGH = ChangeFacts("normal", "high", "s-hq", None)


def test_req_chg_041_ac1_the_mapped_board_reviews_and_says_why() -> None:
    chosen = choose([DEFAULT, EMERGENCY, PAYROLL], HIGH)
    assert (chosen.board_ids, chosen.reason) == (("b-pay",), "mapped")


def test_req_chg_041_ac2_nothing_matches_so_the_default_reviews() -> None:
    low = ChangeFacts("normal", "low", "s-hq", None)
    chosen = choose([DEFAULT, EMERGENCY, PAYROLL], low)
    assert (chosen.board_ids, chosen.reason) == (("b-cab",), "default")
    assert chosen.without_members == ("b-cab",)  # "CAB has no members" (Appendix A)


def test_the_first_match_or_every_match() -> None:
    both = _board("b-all-high", None, 3, {"risk_levels": ["high"]})
    assert choose([PAYROLL, both], HIGH).board_ids == ("b-pay",)
    assert choose([PAYROLL, both], HIGH, every_match=True).board_ids == ("b-pay", "b-all-high")


def test_a_mapping_matches_on_every_key_it_names() -> None:
    assert matches({"change_types": ["emergency"]}, ChangeFacts("emergency", None, None, None))
    assert not matches({"change_types": ["emergency"]}, HIGH)
    assert not matches({}, HIGH)  # an empty mapping names nothing
    assert not matches(None, HIGH)


def test_a_mapping_has_known_keys_and_lists_of_strings() -> None:
    assert mapping_problems({"risk_levels": ["high"]}) == []
    assert mapping_problems(None) == []
    assert set(mapping_problems({"services": ["x"], "risk_levels": "high"})) == {
        ("mapping.services", "not_a_field"),
        ("mapping.risk_levels", "invalid_value"),
    }
