from app.shared.domain import prefix_problems


def test_a_prefix_is_two_to_six_capital_letters() -> None:
    assert prefix_problems("INC") == []
    assert prefix_problems("inc") == ["invalid_prefix"]
    assert prefix_problems("TOOLONGX") == ["invalid_prefix"]
