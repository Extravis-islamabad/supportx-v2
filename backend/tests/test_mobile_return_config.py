"""The mobile sign-in returns only to a web link on the SupportX host (ADR-044 item 3)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize(
    "uri",
    ["supportx://auth", "exp://127.0.0.1:8081/--/auth", "https://sx.example.com", "/mobile/auth"],
)
def test_a_custom_scheme_or_a_bare_host_is_refused(uri: str) -> None:
    with pytest.raises((ValidationError, ValueError), match="ADR-044"):
        Settings(profile="test", mobile_redirect_uri=uri)


def test_a_link_on_the_host_is_kept() -> None:
    uri = "https://sx.example.com/mobile/auth"
    assert Settings(profile="test", mobile_redirect_uri=uri).mobile_redirect_uri == uri
