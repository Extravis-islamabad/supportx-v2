"""The disposal record's rules (REQ-AST-017), without I/O."""

from datetime import date

from app.modules.assets.domain.disposal import disposal_problems

TODAY = date(2026, 11, 6)


def _codes(**kw: object) -> dict[str, str]:
    base: dict[str, object] = {
        "disposed_on": TODAY,
        "today": TODAY,
        "method": "recycling",
        "reason": "End of life",
        "cost": None,
        "currency": None,
    }
    base.update(kw)
    return {p.field: p.code for p in disposal_problems(**base)}  # type: ignore[arg-type]  # test kwargs


def test_a_complete_record_has_no_problems() -> None:
    assert _codes() == {}
    assert _codes(cost="45.50", currency="PKR") == {}


def test_every_problem_is_reported_at_once() -> None:
    assert _codes(disposed_on=None, method=None, reason="  ") == {
        "disposed_on": "required",
        "method": "required",
        "reason": "required",
    }


def test_dates_methods_amounts_and_currencies_are_checked() -> None:
    assert _codes(disposed_on=date(2026, 11, 7)) == {"disposed_on": "date_in_future"}
    assert _codes(method="burned") == {"method": "invalid_choice"}
    assert _codes(reason="x" * 1001) == {"reason": "value_too_long"}
    assert _codes(cost="-1", currency="PKR") == {"cost": "out_of_range"}
    assert _codes(cost="1.005", currency="PKR") == {"cost": "too_many_decimals"}
    assert _codes(cost="abc", currency="PKR") == {"cost": "out_of_range"}
    assert _codes(cost="NaN", currency="PKR") == {"cost": "out_of_range"}
    assert _codes(cost="10") == {"currency": "required"}
    assert _codes(cost="10", currency="pkr") == {"currency": "currency_unknown"}
