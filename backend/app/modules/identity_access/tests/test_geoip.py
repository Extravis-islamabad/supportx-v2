"""The GeoIP reader (WP-057 S2b, D-170): any failure is "no place", never an error.

The real database is ~126 MB and not in the repository. Set SUPPORTX_GEOIP_TEST_DB to a DB-IP Lite
city file to also run the lookup against it.
"""

import ipaddress
import os
from pathlib import Path

import pytest

from app.modules.identity_access.domain.place import GeoHit
from app.modules.identity_access.infra.geoip import GeoIp, _hit

PUBLIC = ipaddress.ip_address("8.8.8.8")


def test_no_setting_means_no_place() -> None:
    geo = GeoIp(None)
    assert geo.lookup(PUBLIC) is None
    assert geo.built_at() is None


def test_a_missing_or_damaged_file_means_no_place(tmp_path: Path) -> None:
    assert GeoIp(tmp_path / "absent.mmdb").lookup(PUBLIC) is None
    damaged = tmp_path / "damaged.mmdb"
    damaged.write_bytes(b"not a database" * 100)
    geo = GeoIp(damaged)
    assert geo.lookup(PUBLIC) is None
    assert geo.lookup(PUBLIC) is None  # tried once, then remembered: no retry per sign-in
    assert geo._failed  # noqa: SLF001 - the remembered failure


def test_the_record_layout_gives_the_english_city_and_the_country_code() -> None:
    record = {
        "city": {"names": {"en": "Lahore", "de": "Lahore"}},
        "country": {"iso_code": "PK", "names": {"en": "Pakistan"}},
    }
    assert _hit(record) == GeoHit(city="Lahore", country="PK")
    assert _hit({"country": {"iso_code": "PK"}}) == GeoHit(city=None, country="PK")
    nothing: object
    for nothing in (None, [], "x", {}, {"city": "Lahore"}, {"city": {"names": {"de": "x"}}}):
        assert _hit(nothing) is None


@pytest.mark.skipif(
    not os.environ.get("SUPPORTX_GEOIP_TEST_DB"),
    reason="set SUPPORTX_GEOIP_TEST_DB to a DB-IP file",
)
def test_a_real_database_answers_a_public_address() -> None:
    geo = GeoIp(Path(os.environ["SUPPORTX_GEOIP_TEST_DB"]))
    hit = geo.lookup(PUBLIC)
    assert hit is not None
    assert hit.country is not None
    assert len(hit.country) == 2
    assert geo.built_at() is not None
    assert geo.lookup(ipaddress.ip_address("10.1.2.3")) is None  # the database has no private data
