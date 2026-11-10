"""The dev-only quick sign-in can't be switched on outside the local dev stack (D-151)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from conftest import make_settings

ON = {
    "dev_quick_sign_in": True,
    "showcase_password": "Showcase-Dev-2026!",
    "showcase_totp_key": "k" * 40,
}


@pytest.mark.parametrize("profile", ["test", "production"])
def test_any_profile_but_dev_refuses_to_start_with_it(profile: str) -> None:
    with pytest.raises((ValidationError, ValueError), match="D-151"):
        Settings(profile=profile, **ON)  # type: ignore[arg-type]  # pydantic-settings init kwargs


@pytest.mark.parametrize("field", ["showcase_password", "showcase_totp_key"])
def test_the_persona_secrets_are_refused_outside_dev_too(field: str) -> None:
    with pytest.raises((ValidationError, ValueError), match="dev stack only"):
        Settings(profile="test", **{field: ON[field]})  # type: ignore[arg-type]


def test_on_in_dev_needs_both_secrets() -> None:
    with pytest.raises((ValidationError, ValueError), match="SHOWCASE_TOTP_KEY"):
        Settings(profile="dev", dev_quick_sign_in=True, showcase_password="x" * 16)  # type: ignore[arg-type]


def test_the_dev_profile_with_everything_starts() -> None:
    settings = make_settings(profile="dev", **ON)
    assert settings.dev_quick_sign_in
    create_app(settings)  # starts; the routes still answer 404 off the local address
