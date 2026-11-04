"""Instance settings rules (WP-042; REQ-ADM-049, 050, 052). No I/O."""

from app.modules.organization.domain.instance import language_for, problems


def test_good_values_pass() -> None:
    assert (
        problems(
            {
                "time_zone": "Asia/Karachi",
                "week_start": "monday",
                "date_format": "dd/mm/yyyy",
                "time_format": "24h",
                "country": "PK",
                "fiscal_year_start_month": 7,
                "contact_email": "it@example.com",
                "base_currency": "PKR",
                "languages": ["en", "ur"],
                "default_language": "ur",
            }
        )
        == []
    )


def test_each_bad_value_is_named_at_its_field() -> None:
    found = problems(
        {
            "time_zone": "Mars/Olympus",
            "week_start": "friday",
            "country": "pak",
            "fiscal_year_start_month": 13,
            "contact_email": "nope",
            "base_currency": "XYZ",
            "languages": ["ar"],  # English is always offered
            "default_language": "ur",
        }
    )
    assert dict(found) == {
        "time_zone": "time_zone_unknown",
        "week_start": "week_start_unknown",
        "country": "country_invalid",
        "fiscal_year_start_month": "month_out_of_range",
        "contact_email": "email_invalid",
        "base_currency": "currency_unknown",
        "languages": "languages_invalid",
        "default_language": "default_language_not_offered",
    }


def test_a_language_switched_off_falls_back_to_the_default() -> None:
    assert language_for("ur", ("en", "ar"), "ar") == "ar"
    assert language_for("ar", ("en", "ar"), "en") == "ar"
    assert language_for(None, ("en",), "en") == "en"
