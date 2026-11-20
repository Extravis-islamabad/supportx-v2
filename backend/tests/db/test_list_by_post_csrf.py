"""The POST list is a read, but a cookie session still needs its CSRF token (lanes B and C).

Through the real browser session (the BFF test world): with the token the list answers; without
it the request is refused before anything is read.
"""

import pytest

from tests.db.test_auth_bff import Bff, bff  # noqa: F401 - the fixture, reused

pytestmark = pytest.mark.db


async def test_a_post_list_without_the_csrf_token_is_refused(bff: Bff) -> None:  # noqa: F811 - fixture
    response = await bff.login(
        bff.user("a", email="admin@demo.test", roles=("tenant_admin", "technician"))
    )
    assert response.status_code == 302, response.text
    csrf = await bff.csrf()
    refused = await bff.client.post("/api/v1/incidents/list", json={})
    assert refused.status_code == 403, refused.text
    allowed = await bff.client.post(
        "/api/v1/incidents/list", json={}, headers={"X-CSRF-Token": csrf}
    )
    assert allowed.status_code == 200, allowed.text
    assert "Idempotency-Key" not in allowed.request.headers  # a read: none was needed
