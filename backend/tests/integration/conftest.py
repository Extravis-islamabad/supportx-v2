"""Fixtures for integration tests (see keycloak_container.py)."""

from collections.abc import Iterator

import pytest

from tests.integration import keycloak_container
from tests.integration.keycloak_container import PrivateKeycloak


@pytest.fixture(scope="session")
def private_keycloak() -> Iterator[PrivateKeycloak]:
    """This process's own Keycloak with the dev realm; never the shared dev Keycloak."""
    started = keycloak_container.start()
    if started is None:
        pytest.skip("Docker is not available for a private Keycloak")
    try:
        yield started
    finally:
        keycloak_container.stop(started)
