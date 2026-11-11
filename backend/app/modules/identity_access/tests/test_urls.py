"""Console and portal URLs when both share one host (WP-014: the portal under /portal)."""

from typing import Any

from app.core.config import Settings
from app.modules.identity_access.domain.identity import safe_return_to
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
    # The console's hand-off of a requester-only person (SessionGate: `/?from=console`) lands on
    # the portal's home, not on the shared host's root, which is the console (nightly roles e2e).
    assert auth.landing("portal", "/?from=console") == (
        "https://desk.example.com/portal/?from=console"
    )
    assert auth.landing("portal", "/#top") == "https://desk.example.com/portal/#top"
    assert auth.landing("console", "/?from=portal") == "https://desk.example.com/?from=portal"
    # Which UI is never read from the query: only the named app (`app=console|portal`, set by the
    # caller) picks the base path, so a console root with any query stays on the console.
    assert auth.landing("console", "/?tab=x") == "https://desk.example.com/?tab=x"
    assert auth.landing("console", "/?from=console") == "https://desk.example.com/?from=console"


def test_landing_never_leaves_the_host() -> None:
    """The stored return path went through safe_return_to; landing adds no way out either."""
    auth = service(
        console_url="https://desk.example.com", portal_url="https://desk.example.com/portal"
    )
    for sneaky in ("//evil.example/", "/\\evil.example", "https://evil.example/", "/%2F%2Fevil"):
        landed = auth.landing("portal", safe_return_to(sneaky))
        assert landed == "https://desk.example.com/portal/", (sneaky, landed)


def test_separate_dev_origins_are_unchanged() -> None:
    auth = service(console_url="http://localhost:5173", portal_url="http://localhost:5174")
    assert auth.allowed_origins == frozenset({"http://localhost:5173", "http://localhost:5174"})
    assert auth.landing("portal", "/") == "http://localhost:5174/"
    assert auth.landing("console", "/users") == "http://localhost:5173/users"
    assert auth.landing("portal", "/?from=console") == "http://localhost:5174/?from=console"
