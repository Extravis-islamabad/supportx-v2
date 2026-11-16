"""The pure parts of sealed custom values (WP-057 S3b-2)."""

from app.modules.work_items.service.custom_values import _blind_text, is_sealed


def test_only_sx2_text_counts_as_sealed() -> None:
    assert is_sealed("sx2:abc")
    assert not is_sealed("abc")
    assert not is_sealed(42)
    assert not is_sealed(None)
    assert not is_sealed(["sx2:abc"])


def test_a_filter_compares_text_as_itself_and_other_values_as_json() -> None:
    assert _blind_text("B7") == "B7"
    assert _blind_text(7) == "7"
    assert _blind_text(["a", "b"]) == '["a", "b"]'
