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

    # Database (WP-005). `database_url` is the application role (supportx_app) through PgBouncer
    # in transaction mode; `migration_database_url` is supportx_migrator straight to PostgreSQL,
    # used only by Alembic and dev tooling, never by the running API.
    migration_database_url: SecretStr | None = None
    db_pool_size: int = Field(default=10, ge=1, le=200)
    db_max_overflow: int = Field(default=10, ge=0, le=200)
    db_pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)

    # Authentication (WP-006): OIDC against Keycloak through the BFF (architecture.md §11.1).
    # The issuer is the realm URL, e.g. http://localhost:28080/realms/supportx.
    oidc_issuer: str | None = None
    oidc_console_client_id: str = "supportx-console"
    oidc_console_client_secret: SecretStr | None = None
    oidc_portal_client_id: str = "supportx-portal"
    oidc_portal_client_secret: SecretStr | None = None
    oidc_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    # Public base URLs of the two UIs. The OIDC callback is <base>/api/v1/auth/callback (same
    # origin as the UI, D-009) and returnTo paths are resolved against them.
    console_url: str = "http://localhost:5173"
    portal_url: str = "http://localhost:5174"

    # BFF sessions: opaque cookie, records encrypted in Valkey (D-021).
    session_secret: SecretStr | None = None
    session_idle_timeout_seconds: int = Field(default=1800, ge=60, le=86400)
    session_absolute_timeout_seconds: int = Field(default=43200, ge=300, le=7 * 86400)
    # None = derived: Secure everywhere except the dev profile (plain-http localhost).
    session_cookie_secure: bool | None = None

    # Dev-only escape hatch: trust an X-Tenant-ID header when there is no session. Off by default;
    # honoured only in the dev and test profiles and ALWAYS ignored in production.
    dev_tenant_header: bool = False

    # OpenTelemetry: tracing is always set up; spans are exported only when an exporter is chosen.
    tracing_enabled: bool = True
    trace_exporter: TraceExporter = "none"

    @model_validator(mode="after")
    def _production_requires_backing_services(self) -> Self:
        if self.profile == "production":
            required = (
                "database_url",
                "valkey_url",
                "nats_url",
                "oidc_issuer",
                "oidc_console_client_secret",
                "oidc_portal_client_secret",
                "session_secret",
            )
            missing = [name for name in required if getattr(self, name) is None]
            if missing:
                names = ", ".join(f"SUPPORTX_{m.upper()}" for m in missing)
                msg = f"production profile requires: {names}"
                raise ValueError(msg)
            if self.session_cookie_secure is False:
                msg = "SUPPORTX_SESSION_COOKIE_SECURE cannot be false in production"
                raise ValueError(msg)
            if self.session_secret is not None and len(self.session_secret.get_secret_value()) < 32:  # noqa: PLR2004 - minimum key material
                msg = "SUPPORTX_SESSION_SECRET must be at least 32 characters in production"
                raise ValueError(msg)
        return self

    @property
    def effective_session_cookie_secure(self) -> bool:
        """Secure cookies everywhere except the plain-http dev profile (unless overridden)."""
        if self.profile == "production":
            return True
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.profile != "dev"

    @property
    def tenant_header_enabled(self) -> bool:
        """Whether X-Tenant-ID may be trusted: explicit opt-in, dev/test only, never production."""
        return self.dev_tenant_header and self.profile in {"dev", "test"}

    @property
    def auth_configured(self) -> bool:
        """Whether the BFF login can run (Keycloak, Valkey and a session key are configured)."""
        return (
            self.oidc_issuer is not None
            and self.valkey_url is not None
            and self.session_secret is not None
        )

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
