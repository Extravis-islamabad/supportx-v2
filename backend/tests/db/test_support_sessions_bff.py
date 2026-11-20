"""Vendor support's per-request check costs ordinary sessions nothing (WP-057 S4c-1, lane B (6)).

Every request on a vendor_support session asks its grant (support_grants.request_refusal); every
other session pays one in-memory comparison of its stored user type and never reaches it. Proven
here with a real BFF sign-in: the check is made to fail if anyone ever calls it.
"""

from typing import Any

import pytest

from app.modules.identity_access.service import support_grants
from tests.db.test_auth_bff import Bff, bff  # noqa: F401 - the fixture, reused

pytestmark = pytest.mark.db


async def test_an_ordinary_session_never_reaches_the_support_check(
    bff: Bff,  # noqa: F811 - the reused fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def never(*_args: Any, **_kwargs: Any) -> None:  # noqa: ANN401 - any arguments
        message = "an ordinary session reached the vendor support check"
        raise AssertionError(message)

    monkeypatch.setattr(support_grants, "request_refusal", never)
    assert (await bff.login(bff.user("a"))).status_code == 302
    for _ in range(20):
        me = await bff.me()
        assert me.status_code == 200, me.text
