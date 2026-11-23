"""DB tests: required erasure ports not built yet are stood in (tests/erasure_pending.py)."""

from collections.abc import Iterator

import pytest

from tests.erasure_pending import pending_ports_stood_in


@pytest.fixture(autouse=True)
def _pending_erasure_ports() -> Iterator[None]:
    """No-op stand-ins for `assets` and `service_catalog` until their real ports exist."""
    with pending_ports_stood_in():
        yield
