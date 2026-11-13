"""Known-device fingerprints (WP-057 S2b-1, REQ-SEC-033): keyed, per person, network-wide."""

import uuid

from app.modules.identity_access.domain.known_device import (
    FINGERPRINT_BYTES,
    fingerprint,
    fingerprints,
    network_part,
)

KEY = b"k" * 32
OLD_KEY = b"o" * 32
AMAL = uuid.UUID("00000000-0000-7000-8000-0000000000b1")
BILAL = uuid.UUID("00000000-0000-7000-8000-0000000000b2")


def test_the_network_is_the_24_or_the_48() -> None:
    assert network_part("10.1.2.3") == "10.1.2.0/24"
    assert network_part("::ffff:10.1.2.3") == "10.1.2.0/24"
    assert network_part("2001:db8:1:2::5") == "2001:db8:1::/48"
    assert network_part(None) is None
    assert network_part("nonsense") is None


def test_the_same_browser_on_the_same_network_is_the_same_device() -> None:
    here = fingerprint(KEY, AMAL, "chrome:windows", "203.0.113.7")
    assert here is not None
    assert len(here) == FINGERPRINT_BYTES
    assert fingerprint(KEY, AMAL, "chrome:windows", "203.0.113.200") == here  # same /24
    assert fingerprint(KEY, AMAL, "chrome:windows", "198.51.100.7") != here  # another network
    assert fingerprint(KEY, AMAL, "firefox:windows", "203.0.113.7") != here  # another browser
    assert fingerprint(KEY, BILAL, "chrome:windows", "203.0.113.7") != here  # another person
    assert fingerprint(OLD_KEY, AMAL, "chrome:windows", "203.0.113.7") != here  # another key


def test_nothing_to_go_on_means_no_fingerprint() -> None:
    assert fingerprint(KEY, AMAL, None, None) is None
    assert fingerprint(KEY, AMAL, None, "203.0.113.7") is not None
    assert fingerprint(KEY, AMAL, "chrome:windows", None) is not None
    assert fingerprints([KEY, OLD_KEY], AMAL, None, None) == ()


def test_every_listed_key_gives_its_own_fingerprint_newest_first() -> None:
    both = fingerprints([KEY, OLD_KEY], AMAL, "chrome:windows", "203.0.113.7")
    assert both == (
        fingerprint(KEY, AMAL, "chrome:windows", "203.0.113.7"),
        fingerprint(OLD_KEY, AMAL, "chrome:windows", "203.0.113.7"),
    )
