"""Worklog costs, the pure part (WP-046a S3, REQ-INC-068)."""

from decimal import Decimal

from app.modules.work_items.domain.parts import CostLine, cost_line, technician_cost


def test_ac1_ninety_minutes_at_forty_an_hour_costs_sixty() -> None:
    assert technician_cost(90, Decimal(40)) == Decimal("60.00")
    assert technician_cost(1, Decimal(10)) == Decimal("0.17")  # half up, to the cent


def test_a_cost_line_in_the_base_currency_or_converted_with_the_entered_rate() -> None:
    assert cost_line({"amount": Decimal("12.345")}, "PKR") == CostLine(Decimal("12.35"))
    converted = cost_line(
        {
            "original_amount": Decimal(10),
            "original_currency": "USD",
            "exchange_rate": Decimal("278.5"),
            "note": "Cable",
        },
        "PKR",
    )
    assert converted == CostLine(Decimal("2785.00"), Decimal(10), "USD", Decimal("278.5"), "Cable")


def test_a_cost_line_names_its_first_problem() -> None:
    assert cost_line({"amount": Decimal(-1)}, "PKR") == ("amount", "invalid_value")
    assert cost_line({"original_amount": Decimal(1), "original_currency": "usd"}, "PKR") == (
        "original_currency",
        "invalid_value",
    )
    assert cost_line({"original_amount": Decimal(1), "original_currency": "USD"}, "PKR") == (
        "exchange_rate",
        "required",
    )
