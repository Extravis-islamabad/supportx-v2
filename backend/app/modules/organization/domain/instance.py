"""The tenant's instance settings (WP-042; REQ-ADM-049, 050, 052). Pure.

The defaults for people and sites (time zone, week start, date and time formats, country, fiscal
year), the base currency, and the languages the tenant offers. A person's own choice wins, then
their site's, then these (REQ-ADM-059 AC3).
"""

import re
import zoneinfo
from collections.abc import Mapping
from typing import Any

LANGUAGES = ("en", "ar", "ur")
REQUIRED_LANGUAGE = "en"  # always offered: the reference language of every label
WEEK_STARTS = ("monday", "sunday", "saturday")
DATE_FORMATS = ("dd/mm/yyyy", "mm/dd/yyyy", "yyyy-mm-dd", "dd.mm.yyyy")
TIME_FORMATS = ("24h", "12h")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ISO 4217 codes in use (no funds codes, no precious metals).
CURRENCIES = frozenset(
    [
        "AED",
        "AFN",
        "ALL",
        "AMD",
        "ANG",
        "AOA",
        "ARS",
        "AUD",
        "AWG",
        "AZN",
        "BAM",
        "BBD",
        "BDT",
        "BGN",
        "BHD",
        "BIF",
        "BMD",
        "BND",
        "BOB",
        "BRL",
        "BSD",
        "BTN",
        "BWP",
        "BYN",
        "BZD",
        "CAD",
        "CDF",
        "CHF",
        "CLP",
        "CNY",
        "COP",
        "CRC",
        "CUP",
        "CVE",
        "CZK",
        "DJF",
        "DKK",
        "DOP",
        "DZD",
        "EGP",
        "ERN",
        "ETB",
        "EUR",
        "FJD",
        "FKP",
        "GBP",
        "GEL",
        "GHS",
        "GIP",
        "GMD",
        "GNF",
        "GTQ",
        "GYD",
        "HKD",
        "HNL",
        "HTG",
        "HUF",
        "IDR",
        "ILS",
        "INR",
        "IQD",
        "IRR",
        "ISK",
        "JMD",
        "JOD",
        "JPY",
        "KES",
        "KGS",
        "KHR",
        "KMF",
        "KPW",
        "KRW",
        "KWD",
        "KYD",
        "KZT",
        "LAK",
        "LBP",
        "LKR",
        "LRD",
        "LSL",
        "LYD",
        "MAD",
        "MDL",
        "MGA",
        "MKD",
        "MMK",
        "MNT",
        "MOP",
        "MRU",
        "MUR",
        "MVR",
        "MWK",
        "MXN",
        "MYR",
        "MZN",
        "NAD",
        "NGN",
        "NIO",
        "NOK",
        "NPR",
        "NZD",
        "OMR",
        "PAB",
        "PEN",
        "PGK",
        "PHP",
        "PKR",
        "PLN",
        "PYG",
        "QAR",
        "RON",
        "RSD",
        "RUB",
        "RWF",
        "SAR",
        "SBD",
        "SCR",
        "SDG",
        "SEK",
        "SGD",
        "SHP",
        "SLE",
        "SOS",
        "SRD",
        "SSP",
        "STN",
        "SVC",
        "SYP",
        "SZL",
        "THB",
        "TJS",
        "TMT",
        "TND",
        "TOP",
        "TRY",
        "TTD",
        "TWD",
        "TZS",
        "UAH",
        "UGX",
        "USD",
        "UYU",
        "UZS",
        "VES",
        "VND",
        "VUV",
        "WST",
        "XAF",
        "XCD",
        "XOF",
        "XPF",
        "YER",
        "ZAR",
        "ZMW",
        "ZWL",
    ]
)


# field → (allowed values, problem code) for the fields that are one of a known set.
_CHOICES: dict[str, tuple[object, str]] = {
    "week_start": (WEEK_STARTS, "week_start_unknown"),
    "date_format": (DATE_FORMATS, "date_format_unknown"),
    "time_format": (TIME_FORMATS, "time_format_unknown"),
    "base_currency": (CURRENCIES, "currency_unknown"),
}
_MONTHS = range(1, 13)


def _languages(values: Mapping[str, Any]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    offered = list(values.get("languages") or LANGUAGES)
    if "languages" in values and (
        any(lang not in LANGUAGES for lang in offered) or REQUIRED_LANGUAGE not in offered
    ):
        found.append(("languages", "languages_invalid"))
    if "default_language" in values and values["default_language"] not in offered:
        found.append(("default_language", "default_language_not_offered"))
    return found


def problems(values: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(field, code) for each value that is not allowed, in a stable order."""
    found: list[tuple[str, str]] = []
    zone = values.get("time_zone")
    if zone is not None and zone not in zoneinfo.available_timezones():
        found.append(("time_zone", "time_zone_unknown"))
    found += [
        (field, code)
        for field, (allowed, code) in _CHOICES.items()
        if field in values and values[field] not in allowed  # type: ignore[operator]  # tuples and sets
    ]
    if values.get("country") is not None and not _COUNTRY.fullmatch(str(values["country"])):
        found.append(("country", "country_invalid"))
    if "fiscal_year_start_month" in values and values["fiscal_year_start_month"] not in _MONTHS:
        found.append(("fiscal_year_start_month", "month_out_of_range"))
    email = values.get("contact_email")
    if email is not None and not _EMAIL.fullmatch(str(email)):
        found.append(("contact_email", "email_invalid"))
    return found + _languages(values)


def language_for(chosen: str | None, offered: tuple[str, ...], default: str) -> str:
    """A person's language: their choice if the tenant offers it, else the tenant's default."""
    return chosen if chosen in offered else default
