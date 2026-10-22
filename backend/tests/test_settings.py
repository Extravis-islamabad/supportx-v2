from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


def test_defaults_follow_the_profile(
    settings_factory: Callable[..., Settings],
    production_settings: Callable[..., Settings],
) -> None:
    dev = settings_factory(profile="dev")
    assert dev.effective_log_format == "console"
    assert dev.effective_api_docs_enabled is True

    production = production_settings()
    assert production.effective_log_format == "json"
    assert production.effective_api_docs_enabled is False


def test_explicit_values_override_profile_defaults(
    settings_factory: Callable[..., Settings],
) -> None:
    settings = settings_factory(profile="dev", log_format="json", api_docs_enabled=False)
    assert settings.effective_log_format == "json"
    assert settings.effective_api_docs_enabled is False


def test_production_requires_every_backing_service(
    settings_factory: Callable[..., Settings],
) -> None:
    with pytest.raises(
        ValidationError, match="SUPPORTX_VALKEY_URL, SUPPORTX_NATS_URL, SUPPORTX_OIDC"
    ):
        settings_factory(profile="production", database_url="postgresql://u:p@db/x")


def test_production_session_rules(production_settings: Callable[..., Settings]) -> None:
    settings = production_settings()
    assert settings.effective_session_cookie_secure is True
    assert settings.auth_configured is True
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        production_settings(session_cookie_secure=False)
    with pytest.raises(ValidationError, match="at least 32 characters"):
        production_settings(session_secret="short")


def test_cookie_secure_defaults(settings_factory: Callable[..., Settings]) -> None:
    assert settings_factory(profile="dev").effective_session_cookie_secure is False
    assert settings_factory(profile="test").effective_session_cookie_secure is True
    assert settings_factory(
        profile="dev", session_cookie_secure=True
    ).effective_session_cookie_secure


def test_invalid_values_fail_at_startup(settings_factory: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError):
        settings_factory(profile="staging")
    with pytest.raises(ValidationError):
        settings_factory(http_port=0)


def test_reads_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPPORTX_LOG_LEVEL", "debug")
    monkeypatch.setenv("SUPPORTX_READINESS_TIMEOUT_SECONDS", "0.5")
    settings = Settings.load(env_file=None)
    assert settings.log_level == "debug"
    assert settings.readiness_timeout_seconds == 0.5


def test_reads_dotenv_file_but_environment_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SUPPORTX_SERVICE_NAME=from-file\nSUPPORTX_LOG_LEVEL=error\n")
    monkeypatch.setenv("SUPPORTX_LOG_LEVEL", "warning")
    settings = Settings.load(env_file=env_file)
    assert settings.service_name == "from-file"
    assert settings.log_level == "warning"


def test_secrets_never_appear_in_repr_or_dump(settings_factory: Callable[..., Settings]) -> None:
    settings = settings_factory(database_url="postgresql://app:hunter2@db/x")
    assert "hunter2" not in repr(settings)
    assert "hunter2" not in str(settings.model_dump())
    assert settings.database_url is not None
    assert settings.database_url.get_secret_value().endswith("@db/x")


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()
