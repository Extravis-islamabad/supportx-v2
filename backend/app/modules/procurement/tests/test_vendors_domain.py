"""Vendor field rules (REQ-PUR-001), no I/O."""

from app.modules.procurement.domain.vendors import NAME_MAX, clean_vendor


def test_text_is_trimmed_and_blank_means_none() -> None:
    cleaned, problems = clean_vendor({"name": "  Acme  Co ", "address": "  ", "currency": "PKR"})
    assert problems == []
    assert cleaned == {"name": "Acme Co", "address": None, "currency": "PKR"}


def test_only_the_fields_sent_are_cleaned() -> None:
    cleaned, problems = clean_vendor({"is_active": False})
    assert (cleaned, problems) == ({"is_active": False}, [])


def test_shapes_and_limits_are_checked() -> None:
    _, problems = clean_vendor(
        {
            "name": "x" * (NAME_MAX + 1),
            "currency": "usd",
            "email": "no-at-sign",
            "fax": "fax me",
            "website": "ftp://acme.test",
        }
    )
    assert {(p.field, p.code) for p in problems} == {
        ("name", "value_too_long"),
        ("currency", "invalid_currency"),
        ("email", "invalid_email"),
        ("fax", "invalid_phone"),
        ("website", "invalid_website"),
    }
    _, problems = clean_vendor({"name": "   "})
    assert [(p.field, p.code) for p in problems] == [("name", "required")]
