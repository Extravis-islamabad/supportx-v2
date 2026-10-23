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

    # Event bus (WP-007, docs/architecture/events.md). The relay connects as supportx_relay
    # straight to PostgreSQL, never through PgBouncer: LISTEN needs a session-level connection.
    # Only the relay process reads `relay_database_url`.
    relay_database_url: SecretStr | None = None
    # Prefix for every stream, subject and bucket name. Empty in real deployments; the test suite
    # sets a random one so it never touches the dev stack's streams.
    events_namespace: str = Field(default="", pattern=r"^[a-z0-9_]*$", max_length=24)
    events_stream_max_age_hours: int = Field(default=168, ge=1)
    events_stream_replicas: int = Field(default=1, ge=1, le=5)
    # JetStream drops a second message with the same Nats-Msg-Id (= event ID) inside this window.
    # It must outlast a relay crash and restart, see events.md "Duplicates".
    events_duplicate_window_seconds: int = Field(default=300, ge=10, le=86400)
    dlq_max_age_hours: int = Field(default=720, ge=1)
    relay_batch_size: int = Field(default=200, ge=1, le=5000)
    # LISTEN/NOTIFY wakes the relay at once; this poll only catches a missed notification.
    relay_poll_interval_seconds: float = Field(default=2.0, gt=0, le=60)
    relay_publish_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    outbox_retention_hours: int = Field(default=72, ge=1)
    outbox_purge_interval_seconds: int = Field(default=3600, ge=10)
    # Consumer idempotency records (processed_events) are kept this long, then the relay deletes
    # them (WP-012). Never below 7 days, the event stream's maximum age: a redelivery could still
    # need them (the database enforces the same floor, migration 0010).
    processed_events_retention_days: int = Field(default=30, ge=7)
    consumer_max_attempts: int = Field(default=5, ge=1, le=100)
    consumer_backoff_initial_seconds: float = Field(default=1.0, gt=0)
    consumer_backoff_max_seconds: float = Field(default=60.0, gt=0)
    consumer_ack_wait_seconds: float = Field(default=30.0, ge=1)
    heartbeat_interval_seconds: float = Field(default=5.0, gt=0, le=60)
    heartbeat_stale_seconds: float = Field(default=20.0, gt=0, le=600)
    # Dev-only consumer that logs every event. None = on in the dev profile only; never in
    # production, whatever this says.
    dev_event_logger: bool | None = None

    # API conventions (WP-008, docs/architecture/api-conventions.md).
    # Key for signing list cursors. None = derived from SUPPORTX_SESSION_SECRET; with neither
    # (dev/test without login) a random per-process key is used, so cursors die with the process.
    cursor_secret: SecretStr | None = None
    page_size_default: int = Field(default=50, ge=1, le=500)
    page_size_max: int = Field(default=200, ge=1, le=1000)
    idempotency_ttl_hours: int = Field(default=24, ge=1, le=720)
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    # Requests per window for each route group, per user (or API token) and per tenant. Groups not
    # listed use "default". JSON in the environment, e.g.
    # SUPPORTX_RATE_LIMITS='{"users": {"user": 300, "tenant": 3000}}'.
    rate_limits: dict[str, dict[str, int]] = Field(
        default_factory=lambda: {"default": {"user": 600, "tenant": 6000}}
    )
    # Prefix for every Valkey key the API writes (tests use a random one).
    valkey_key_prefix: str = Field(default="supportx:", max_length=40)

    # Entitlements (WP-009, docs/architecture/entitlements.md). Where licence data comes from:
    # `subscription` = the tenant's plan row in tenant_subscriptions (control-plane data);
    # `licence_file` = a licence document at `licence_file`. Only the licensing module reads
    # these; no other code may branch on them (guard test in app/modules/licensing/tests).
    entitlement_provider: Literal["subscription", "licence_file"] = "subscription"
    licence_file: Path | None = None
    # Per-tenant entitlement cache in Valkey; changes invalidate it at once through the
    # licensing.entitlement.changed event, the TTL only bounds staleness if an event is lost.
    entitlement_cache_ttl_seconds: int = Field(default=300, ge=0, le=86400)

    # Realtime (WP-011, docs/architecture/realtime.md). The API signs Centrifugo connection and
    # subscription tokens with `centrifugo_token_secret` (HS256, same key Centrifugo verifies);
    # the fan-out worker and revocation call Centrifugo's server API at `centrifugo_api_url`.
    centrifugo_api_url: str | None = None
    centrifugo_api_key: SecretStr | None = None
    centrifugo_token_secret: SecretStr | None = None
    centrifugo_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    # Short lifetimes: a token outliving a permission change is cut off by revocation anyway,
    # the expiry only bounds what a lost revocation could leak (architecture.md §8.2).
    realtime_connection_token_ttl_seconds: int = Field(default=900, ge=30, le=86400)
    realtime_subscription_token_ttl_seconds: int = Field(default=300, ge=30, le=86400)
    # Fan-out: list publications to one channel within this window become one message, and a
    # tenant gets at most this many publications per second (the rest are coalesced).
    realtime_coalesce_ms: int = Field(default=250, ge=0, le=5000)
    realtime_tenant_publications_per_second: float = Field(default=200.0, gt=0)

    # OpenTelemetry: tracing is always set up; spans are exported only when an exporter is chosen.
    tracing_enabled: bool = True
    trace_exporter: TraceExporter = "none"
    # Worker metrics (WP-007); `console` prints them periodically. Prometheus export: WP-014.
    metrics_exporter: TraceExporter = "none"

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
                "centrifugo_api_url",
                "centrifugo_api_key",
                "centrifugo_token_secret",
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
        if self.entitlement_provider == "licence_file" and self.licence_file is None:
            msg = "SUPPORTX_ENTITLEMENT_PROVIDER=licence_file requires SUPPORTX_LICENCE_FILE"
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
    def effective_dev_event_logger(self) -> bool:
        """The dev event logger runs in dev by default, on request in test, never in production."""
        if self.profile == "production":
            return False
        if self.dev_event_logger is not None:
            return self.dev_event_logger
        return self.profile == "dev"

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
