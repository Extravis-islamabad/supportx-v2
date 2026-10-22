"""Typed, validated runtime settings (architecture.md §6.4; WP-004).

Every setting comes from an environment variable prefixed `SUPPORTX_` (for example
`SUPPORTX_DATABASE_URL`). For local development they may also come from `backend/.env`, which
`make backend-env` generates from the dev stack's `deploy/compose/.env`. Real environment
variables always win over the file.

Profiles select safe defaults: `dev` (console logs, API docs on), `test` (used by the test suite,
which never reads backend/.env) and `production` (JSON logs, docs off, every dependency URL
required). The profile is about
how the process runs, never about SaaS vs on-prem: that difference goes through the entitlement
interface only (CLAUDE.md rule f).
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Profile = Literal["dev", "test", "production"]
LogFormat = Literal["console", "json"]
TraceExporter = Literal["none", "console"]

BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """Process configuration. Secrets are `SecretStr`, so they never appear in repr or logs."""

    model_config = SettingsConfigDict(
        env_prefix="SUPPORTX_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    profile: Profile = "dev"
    service_name: str = "supportx-api"

    http_host: str = "127.0.0.1"
    http_port: int = Field(default=8000, ge=1, le=65535)

    log_level: Literal["debug", "info", "warning", "error"] = "info"
    # None = derived from the profile: console in dev/test, JSON in production.
    log_format: LogFormat | None = None

    api_docs_enabled: bool | None = None

    # Backing services. None means "not configured": readiness reports it instead of crashing.
    database_url: SecretStr | None = None
    valkey_url: SecretStr | None = None
    nats_url: SecretStr | None = None
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    # OpenTelemetry: tracing is always set up; spans are exported only when an exporter is chosen.
    tracing_enabled: bool = True
    trace_exporter: TraceExporter = "none"

    @model_validator(mode="after")
    def _production_requires_backing_services(self) -> Self:
        if self.profile == "production":
            missing = [
                name
                for name in ("database_url", "valkey_url", "nats_url")
                if getattr(self, name) is None
            ]
            if missing:
                names = ", ".join(f"SUPPORTX_{m.upper()}" for m in missing)
                msg = f"production profile requires: {names}"
                raise ValueError(msg)
        return self

    @classmethod
    def load(cls, env_file: Path | None = ENV_FILE, **values: Any) -> Self:  # noqa: ANN401 - validated by pydantic
        """Build settings from env vars, `env_file` (None = read no file) and explicit values."""
        # `_env_file` is a pydantic-settings init argument that mypy cannot see on the model.
        return cls(_env_file=env_file, **values)  # type: ignore[call-arg]

    @property
    def effective_log_format(self) -> LogFormat:
        """Log format after applying the profile default."""
        if self.log_format is not None:
            return self.log_format
        return "json" if self.profile == "production" else "console"

    @property
    def effective_api_docs_enabled(self) -> bool:
        """Swagger UI / OpenAPI JSON are on outside production unless explicitly set."""
        if self.api_docs_enabled is not None:
            return self.api_docs_enabled
        return self.profile != "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, validated once at startup."""
    return Settings()
