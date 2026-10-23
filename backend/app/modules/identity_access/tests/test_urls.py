"""Console and portal URLs when both share one host (WP-014: the portal under /portal)."""

from typing import Any

from app.core.config import Settings
from app.modules.identity_access.service.auth import AuthService
from app.shared.clock import system_clock


def service(**urls: Any) -> AuthService:  # noqa: ANN401 - settings values
    settings = Settings.load(env_file=None, profile="test", **urls)
    # Only the URL helpers are exercised: no store, IdP or database is touched.
    return AuthService(
        settings=settings,
        store=None,  # type: ignore[arg-type]  # unused by the URL helpers
        oidc=None,  # type: ignore[arg-type]  # unused by the URL helpers
        database=None,
        clock=system_clock,
        cookie_name="supportx_session",
    )


def test_one_host_with_the_portal_under_a_path() -> None:
    auth = service(
        console_url="https://desk.example.com/", portal_url="https://desk.example.com/portal"
    )
    # The callback and the Origin check use the host; the API lives at the host's /api.
    assert auth.origin("portal") == "https://desk.example.com"
    assert auth.allowed_origins == frozenset({"https://desk.example.com"})
    # After login: back to the page the user started on, else the UI's own home.
    assert auth.landing("portal", "/") == "https://desk.example.com/portal/"
    assert auth.landing("portal", "/portal/requests?x=1") == (
        "https://desk.example.com/portal/requests?x=1"
    )
    assert auth.landing("console", "/") == "https://desk.example.com/"


def test_separate_dev_origins_are_unchanged() -> None:
    auth = service(console_url="http://localhost:5173", portal_url="http://localhost:5174")
    assert auth.allowed_origins == frozenset({"http://localhost:5173", "http://localhost:5174"})
    assert auth.landing("portal", "/") == "http://localhost:5174/"
    assert auth.landing("console", "/users") == "http://localhost:5173/users"
