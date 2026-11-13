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

import ipaddress
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Profile = Literal["dev", "test", "production"]
LogFormat = Literal["console", "json"]
TraceExporter = Literal["none", "console"]
MetricsExporter = Literal["none", "console", "prometheus"]

# Session key IDs (ADR-048): the codec's own rule (app/shared/crypto/codec.py), repeated here
# because core never imports shared; a test keeps the two equal.
SESSION_KEY_ID_PATTERN = re.compile(r"^[a-z0-9_-]{1,32}$")
# The ID SUPPORTX_SESSION_SECRET has as a one-key ring (D-162).
LEGACY_SESSION_KEY_ID = "legacy"
SESSION_KEY_MIN_LENGTH = 32  # characters, in production (every key, legacy included)
# Every ring key but "legacy" (the pre-D-162 secret, accepted as it was), in every profile.
SESSION_KEY_MIN_BYTES = 32

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
        # A refused setting's error never repeats the input: it holds every secret (D-162).
        hide_input_in_errors=True,
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
    # High availability (WP-014b): Valkey through Sentinel. "host:port,host:port" of the sentinels
    # and the monitored master's name; `valkey_url` then gives only the password, database and
    # TLS (its host is not used). Unset: a single Valkey at `valkey_url`, as before.
    valkey_sentinels: str | None = None
    valkey_sentinel_master: str = Field(default="supportx", min_length=1, max_length=64)
    valkey_sentinel_password: SecretStr | None = None  # None: the same as Valkey's own
    # TLS to Valkey and its sentinels (audit row 5; the chart's internal CA in values-ha.yaml).
    # Set: `valkey_url` must be valkeys:// (or rediss://), and every connection checks the server
    # certificate against this CA and the host name dialled. Unset: as the URL says.
    valkey_tls_ca_file: Path | None = None
    nats_url: SecretStr | None = None
    # TLS to NATS (audit row 5; the chart's internal CA in values-ha.yaml). Set: `nats_url` must
    # be tls://, and the server certificate is checked against this CA and the URL's host name.
    nats_tls_ca_file: Path | None = None
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    # Database (WP-005). `database_url` is the application role (supportx_app) through PgBouncer
    # in transaction mode; `migration_database_url` is supportx_migrator straight to PostgreSQL,
    # used only by Alembic and dev tooling, never by the running API.
    migration_database_url: SecretStr | None = None
    # TLS to PostgreSQL, verified (audit row 5): the CA the server's (or PgBouncer's) certificate
    # chains to. Set: every connection is sslmode verify-full against it (the host name
    # checked). Unset: asyncpg's default, which encrypts when the server offers it but checks
    # nothing. The chart mounts CloudNativePG's own CA, or an external database's.
    database_ssl_root_cert: Path | None = None
    db_pool_size: int = Field(default=10, ge=1, le=200)
    db_max_overflow: int = Field(default=10, ge=0, le=200)
    db_pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    # Client-side limits (WP-014b node-loss test): a connection to a server whose node vanished
    # gets no reset, and without a limit asyncpg waits on the kernel's retries for minutes. Both
    # are generous: they bound a dead server, not slow work. The reporting pool's command limit
    # is always above report_background_timeout_seconds, so no report is cut short by them.
    db_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    db_command_timeout_seconds: float = Field(default=120.0, gt=0, le=3600)

    # Reporting (WP-035, ADR-033). Reports run as supportx_app switched to the read-only
    # supportx_report role, on their own small pool so a burst of reports can never take the
    # connections incident saves need. `reporting_database_url` points the pool at a read replica
    # (HA profiles: CloudNativePG's `-ro` service); unset, it uses `database_url` (single node).
    reporting_database_url: SecretStr | None = None
    reporting_pool_size: int = Field(default=4, ge=1, le=50)
    reporting_max_overflow: int = Field(default=2, ge=0, le=50)
    # Platform maximums (parity file 09, Appendix A); tenants may set lower values.
    report_interactive_timeout_seconds: float = Field(default=30.0, gt=0, le=60)
    report_background_timeout_seconds: float = Field(default=900.0, gt=0, le=3600)
    report_concurrent_per_tenant: int = Field(default=5, ge=1, le=50)

    # Authentication (WP-006): OIDC against Keycloak through the BFF (architecture.md §11.1).
    # The issuer is the realm URL, e.g. http://localhost:28080/realms/supportx.
    oidc_issuer: str | None = None
    # Where the API itself reaches the same realm (back channel: discovery, token, keys, logout),
    # e.g. http://keycloak:8080/auth/realms/supportx inside Kubernetes, where the public issuer
    # (the browser's URL) is not reachable from pods. None = the issuer. ID tokens are still
    # checked against `oidc_issuer` (Keycloak keeps the public issuer with a dynamic back channel).
    oidc_internal_url: str | None = None
    oidc_console_client_id: str = "supportx-console"
    oidc_console_client_secret: SecretStr | None = None
    oidc_portal_client_id: str = "supportx-portal"
    oidc_portal_client_secret: SecretStr | None = None
    oidc_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    # Identity administration (WP-039, ADR-036): the service account SupportX manages SSO,
    # sessions and MFA with through Keycloak's admin API (tooling/keycloak_identity.py sets it up).
    # The admin API is reached on the same base as the back channel. None = not set up: identity
    # settings that need Keycloak answer `identity_admin_not_configured`.
    keycloak_identity_client_id: str = "supportx-identity"
    keycloak_identity_client_secret: SecretStr | None = None
    # Realm settings (WP-039 session 2): the password policy is a realm setting (manage-realm),
    # so it has its own service account, whose secret only the consumers worker holds. None: the
    # policy is saved but not applied (`password_policy_not_configured`).
    keycloak_realm_client_id: str = "supportx-realm"
    keycloak_realm_client_secret: SecretStr | None = None
    # On-prem AD/LDAP (WP-040, D-118): `supportx-federation`, manage-realm only. The chart gives
    # the secret to the consumers worker alone, and only where LDAP is on (never on SaaS).
    keycloak_federation_client_id: str = "supportx-federation"
    keycloak_federation_client_secret: SecretStr | None = None
    # The sign-in log's import of Keycloak's login events (WP-057 S1b): `supportx-events`,
    # view-events only; the chart gives the secret to the consumers worker alone. None: no import
    # (the BFF's own entries are still written).
    keycloak_events_client_id: str = "supportx-events"
    keycloak_events_client_secret: SecretStr | None = None
    # Single sign-on checks fetch the provider's discovery document or SAML metadata through the
    # guarded client (private ranges only via egress_allow, below). This also opens loopback, in
    # the dev and test profiles only, where the test identity provider runs on the same machine.
    sso_fetch_allow_loopback: bool = False
    # Guarded outbound calls (workflow webhooks, outbound webhooks; ADR-043 §8): what the
    # installation opens beyond the public internet, as CIDRs or host names (an on-prem ERP on a
    # private network), and ports beyond 80 and 443. Never a tenant setting. Link-local
    # (cloud metadata), multicast and unspecified addresses stay closed whatever is listed.
    egress_allow: list[str] = Field(default_factory=list)
    egress_extra_ports: list[int] = Field(default_factory=list)
    # Several tenants share this installation's realm (the SaaS cell, WP-014d). A security guard,
    # not a feature switch (D-098): single sign-on may then route only email domains whose
    # ownership the tenant proved. Off for single-tenant installations (on-prem, D-070).
    multi_tenant: bool = False

    # Outgoing mail (WP-039 session 2, D-089 D3, D-099): the one place mail is configured. The
    # mail service sends through it, and the deploy's identity step writes the same server into
    # Keycloak's realm so its password and invitation e-mails leave from the same sender.
    # None host = not configured (`mail_configured()` false; nothing is queued).
    mail_smtp_host: str | None = None
    mail_smtp_port: int = Field(default=587, ge=1, le=65535)
    mail_smtp_security: Literal["starttls", "tls", "none"] = "starttls"
    mail_smtp_username: str | None = None
    mail_smtp_password: SecretStr | None = None
    mail_from_address: str | None = None
    mail_from_name: str = Field(default="SupportX", max_length=120)
    mail_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    # Sending is tried this often before a message is marked failed.
    mail_max_attempts: int = Field(default=5, ge=1, le=20)
    # Bodies and attachments are personal data: cleared this long after sending or failing.
    mail_content_retention_days: int = Field(default=30, ge=1, le=3650)
    # Microsoft 365 and Gmail mailboxes (WP-024 session 2): where the providers answer. The
    # defaults are the public clouds; a sovereign cloud (e.g. Microsoft's national clouds)
    # changes them. Air-gapped installations read mail over IMAP only (D-109 (2)).
    mail_microsoft_login_url: str = "https://login.microsoftonline.com"
    mail_graph_url: str = "https://graph.microsoft.com/v1.0"
    mail_google_authorize_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    mail_google_token_url: str = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL
    mail_gmail_url: str = "https://gmail.googleapis.com/gmail/v1"
    # Public base URLs of the two UIs. They may carry a path: in Kubernetes both share one host,
    # the portal under /portal (WP-014, D3). The OIDC callback is <origin>/api/v1/auth/callback
    # (same origin as the UI, D-009); after login the browser lands on the returnTo path, else on
    # the UI's own base path.
    console_url: str = "http://localhost:5173"
    portal_url: str = "http://localhost:5174"
    # The mobile app's sign-in return address (ADR-044 item 3): the browser is sent here with a
    # one-time hand-off code instead of a cookie. A verified link on the SupportX host (Universal
    # Link / App Link: the host's .well-known files name the trusted app builds), never a custom
    # scheme any app can claim. Fixed per installation (the chart: publicUrl + mobile.returnPath),
    # never taken from a request. Plain http only for the local dev stack and tests.
    mobile_redirect_uri: str = "http://localhost:5173/mobile/auth"
    # Tenant addresses (WP-017): each tenant is also reached on `<slug>.<tenant_base_domain>`
    # (e.g. acme.support.example.com). None = no subdomains (on-prem single installation domain);
    # verified custom domains still resolve. The address only pre-selects where to sign in.
    tenant_base_domain: str | None = None
    # Whether the platform issues certificates for verified custom domains (cert-manager, ACME).
    # False: a verified domain shows "certificate not managed here" until the tenant uploads one
    # or the operator configures it (on-prem single node).
    domain_certificates_managed: bool = False

    # BFF sessions: opaque cookie, records encrypted in Valkey (D-021) under a key ring (D-162,
    # ADR-048). `session_keys`: JSON, newest first, '[{"id": "2026-11", "secret": "..."}, ...]';
    # the newest seals, every listed key still opens (the overlap: keep an old key listed for at
    # least the absolute session lifetime). `session_secret` alone is a one-key ring with the ID
    # "legacy"; with both, the ring is `session_keys`, which may list {"id": "legacy"} (its
    # secret is then `session_secret`) to keep reading records sealed before. `session_secret`
    # also stays the fallback of the cursor, API-key and domain-proof keys below, never the ring:
    # rotating the ring never touches them. See docs/guides/rotating-the-sign-in-key.md.
    session_secret: SecretStr | None = None
    session_keys: SecretStr | None = None
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
    # Custom field index worker (D-088): how often it looks for requests, how long one build may
    # wait for a lock (then "busy") and run (then "timed out").
    index_worker_interval_seconds: float = Field(default=30.0, ge=1, le=600)
    index_lock_timeout_seconds: int = Field(default=60, ge=1, le=3600)
    index_build_timeout_seconds: int = Field(default=7200, ge=60, le=86400)
    # SLA clocks on Temporal (WP-025 session 3, ADR-037): the waker. None: no Temporal here; the
    # sla safety net still fires everything, up to two minutes late (D-115 D5).
    temporal_address: str | None = None  # host:port of the Temporal frontend
    temporal_namespace: str = "supportx"
    temporal_task_queue: str = "sla"
    # Visual workflows' waker (WP-048b, ADR-043 §5): its own queue, its own worker.
    temporal_workflow_task_queue: str = "workflows"
    consumer_backoff_initial_seconds: float = Field(default=1.0, gt=0)
    consumer_backoff_max_seconds: float = Field(default=60.0, gt=0)
    consumer_ack_wait_seconds: float = Field(default=30.0, ge=1)
    heartbeat_interval_seconds: float = Field(default=5.0, gt=0, le=60)
    heartbeat_stale_seconds: float = Field(default=20.0, gt=0, le=600)
    # Event workers ride out PostgreSQL / NATS restarts; past this they exit non-zero so the
    # orchestrator restarts them (workers/resilience.py).
    worker_give_up_seconds: float = Field(default=300.0, gt=0, le=3600)
    # The relay's oldest unpublished event older than this: /ready says event delivery is stalled.
    event_backlog_stalled_seconds: float = Field(default=120.0, gt=0, le=3600)
    # Dev-only consumer that logs every event. None = on in the dev profile only; never in
    # production, whatever this says.
    dev_event_logger: bool | None = None

    # AI gateway (WP-037, architecture.md §12). `fake` replays recorded answers (CI, tests and
    # development without a model); `openai_compatible` talks to a local vLLM or llama.cpp server
    # (or any server speaking that API). `ai_provider_external`: the server is outside the
    # installation, so masking is always on (REQ-AI-018). The key is a secret, never logged.
    ai_provider: Literal["fake", "openai_compatible"] = "fake"
    ai_base_url: str | None = None
    ai_api_key: SecretStr | None = None
    ai_model: str = "fake"
    ai_embedding_model: str = "fake-embeddings"
    # Embeddings from their own server when set (vLLM and the llama.cpp server serve one model
    # each); else from `ai_base_url`. The vectors are 1024 wide (bge-m3, multilingual-e5-large).
    ai_embedding_base_url: str | None = None
    ai_provider_external: bool = False
    ai_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    # JSON file of recorded answers for the fake provider ({"<feature>:<sha256>": "text"}).
    ai_recordings_path: str | None = None
    # The fake's own answer for a prompt it has no recording of: an echo of the prompt, for tests
    # and CI only (SUPPORTX_AI_FAKE_ECHO=true). Off, an installation without a model says "AI
    # isn't set up on this server" and never shows the echo (QA6-AI-01).
    ai_fake_echo: bool = False

    # API conventions (WP-008, docs/architecture/api-conventions.md).
    # Key for signing list cursors. None = derived from SUPPORTX_SESSION_SECRET; with neither
    # (dev/test without login) a random per-process key is used, so cursors die with the process.
    cursor_secret: SecretStr | None = None
    # API keys (WP-041, D-128): the server key their secrets are hashed under (HMAC-SHA-256).
    # Kept outside the database, so a leaked database alone cannot be used to test guesses.
    # Required in production (audit row 26): a key of its own, so the session secret never guards
    # API keys. Dev and test without it derive one from SUPPORTX_SESSION_SECRET; with neither, API
    # keys are unavailable (never a random key: every key would stop working at the next restart).
    # Keys hashed under that derived key before it was set move to it on their next good call while
    # SUPPORTX_SESSION_SECRET stays set (service/api_keys.py). Rotating it ends every key.
    api_key_secret: SecretStr | None = None
    # The key behind custom-domain verification proofs (WP-017). None = SUPPORTX_SESSION_SECRET
    # (the legacy secret, as before D-162), never the session key ring.
    domain_proof_secret: SecretStr | None = None
    page_size_default: int = Field(default=50, ge=1, le=500)
    page_size_max: int = Field(default=200, ge=1, le=1000)
    idempotency_ttl_hours: int = Field(default=24, ge=1, le=720)
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    # Requests per window for each route group, per user (or API token) and per tenant. Groups not
    # listed use "default". JSON in the environment, e.g.
    # SUPPORTX_RATE_LIMITS='{"users": {"user": 300, "tenant": 3000}}'.
    rate_limits: dict[str, dict[str, int]] = Field(
        default_factory=lambda: {
            "default": {"user": 600, "tenant": 6000},
            # Signing out everywhere else (WP-057 S2a, lane B): a few a minute is plenty.
            "auth_sessions": {"user": 10, "tenant": 1000},
        }
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

    # Object storage (S3 API only, D-016; WP-018 adds it, WP-022 reuses it). On-prem: SeaweedFS from
    # the Helm chart; SaaS: the cloud provider's S3; dev: MinIO from Compose. Not configured:
    # features that need it answer 503 `storage_not_configured` (never silently).
    object_storage_endpoint: str | None = None
    object_storage_region: str = "us-east-1"
    object_storage_access_key: SecretStr | None = None
    object_storage_secret_key: SecretStr | None = None
    object_storage_bucket: str = Field(default="supportx", pattern=r"^[a-z0-9][a-z0-9.-]{2,62}$")
    object_storage_timeout_seconds: float = Field(default=10.0, gt=0, le=120)

    # Files (WP-022, ADR-028, docs/architecture/files.md). `files_keys` is the installation key
    # ring that wraps each tenant's data keys: "<key id>:<base64 32 bytes>, ..." with the active
    # key first; older keys stay listed so files they wrapped remain readable (rotation). Back it up
    # with the other secrets: losing it loses every file. Not set: uploads answer 503
    # `files_not_configured` (never plaintext). Scanning: clamd at `files_clamd_address`
    # ("host:port"); with no scanner and `files_scan_required` on (default), files wait as
    # "scanning" and administrators see that no scanner is installed.
    files_keys: SecretStr | None = None
    files_clamd_address: str | None = Field(default=None, pattern=r"^[A-Za-z0-9.-]+:\d{1,5}$")
    files_clamd_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    files_scan_required: bool = True
    files_signature_max_age_days: int = Field(default=7, ge=1, le=90)
    # /ready warns (informational, not unready) once the signatures are older than this: the
    # early sign that freshclam can't reach its mirror, e.g. under the egress allow-list (WP-014b).
    files_signature_ready_warn_hours: int = Field(default=48, ge=1, le=24 * 90)
    files_link_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    # Uploads written to storage at once per API process; more wait their turn (their bodies stay
    # in the network, not in memory). Each holds about one 5 MiB S3 part plus its encryption.
    files_upload_concurrency: int = Field(default=8, ge=1, le=64)

    # Audit log (WP-018, ADR-027, docs/architecture/audit.md). Anchors (signed checkpoints of each
    # tenant's chain) are signed with an Ed25519 installation key, "<key id>:<base64 32-byte
    # seed>", mounted only into the consumers worker. Rotation: set the new key here and move the
    # old key's public half to `audit_trusted_keys` ("<key id>:<base64 public key>, ..."), so
    # checkpoints signed before stay verifiable. No key: anchoring is off and the integrity panel
    # says so (never silently). An HSM or KMS signer can replace the key later (ADR-027).
    audit_signing_key: SecretStr | None = None
    audit_trusted_keys: str = Field(default="", max_length=4000)
    audit_seal_batch_size: int = Field(default=500, ge=1, le=5000)
    audit_anchor_interval_seconds: int = Field(default=3600, ge=60, le=86400)
    # An entry still unsealed after this long raises an alert (product owner: 5 minutes).
    audit_unsealed_alert_seconds: int = Field(default=300, ge=30, le=86400)
    # Module schedules (sealing sweep, anchors, verification, partitions) run in the consumers
    # worker. Off only for tests that count exact stream messages.
    worker_schedules_enabled: bool = True

    # OpenTelemetry: tracing is always set up; spans are exported only when an exporter is chosen.
    tracing_enabled: bool = True
    trace_exporter: TraceExporter = "none"
    # Metrics (WP-007, WP-014): `console` prints them periodically; `prometheus` serves them on
    # an internal port (`metrics_host:metrics_port/metrics`, never routed publicly), together
    # with the workers' /healthz and /readyz probes.
    metrics_exporter: MetricsExporter = "none"
    metrics_host: str = "127.0.0.1"
    metrics_port: int = Field(default=9464, ge=1, le=65535)

    # Dev-only quick sign-in (D-151): one button per showcase persona on /dev/sign-in, so a
    # browser-driving QA run needs no typed password. Only the local Compose stack sets it; any
    # profile but dev refuses to start with it (below), and the chart refuses to render it. The
    # persona password is the showcase seed's (SUPPORTX_SHOWCASE_PASSWORD, deploy/compose/.env).
    dev_quick_sign_in: bool = False
    showcase_password: SecretStr | None = None
    # The dev-only key the personas' authenticator secrets are derived from (D-151): in the dev
    # .env only, never committed, never logged or shown.
    showcase_totp_key: SecretStr | None = None

    @model_validator(mode="after")
    def _dev_quick_sign_in_is_dev_only(self) -> Self:
        if self.dev_quick_sign_in and self.profile != "dev":
            msg = (
                "SUPPORTX_DEV_QUICK_SIGN_IN is for the local dev stack only: it cannot be on with "
                f"the {self.profile} profile (D-151)"
            )
            raise ValueError(msg)
        if self.profile != "dev" and (self.showcase_totp_key or self.showcase_password):
            msg = (
                "SUPPORTX_SHOWCASE_PASSWORD and SUPPORTX_SHOWCASE_TOTP_KEY are for the local dev "
                f"stack only: not with the {self.profile} profile (D-151)"
            )
            raise ValueError(msg)
        if self.dev_quick_sign_in and (
            self.showcase_password is None or self.showcase_totp_key is None
        ):
            msg = (
                "SUPPORTX_DEV_QUICK_SIGN_IN needs SUPPORTX_SHOWCASE_PASSWORD and "
                "SUPPORTX_SHOWCASE_TOTP_KEY (make dev-quick-sign-in)"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _mobile_return_is_a_verified_link(self) -> Self:
        # see ADR-044 item 3: never a custom scheme (supportx://), which any app can claim. https
        # in every installation: the chart builds it from publicUrl, which is https there; http
        # stays possible for the local dev stack and tests, as for console_url.
        parts = urlsplit(self.mobile_redirect_uri)
        if parts.scheme not in {"https", "http"} or not parts.netloc or not parts.path.strip("/"):
            msg = (
                "SUPPORTX_MOBILE_REDIRECT_URI must be an https address on the SupportX host with "
                f"a path, e.g. https://support.example.com/mobile/auth (ADR-044), not "
                f"{self.mobile_redirect_uri!r}"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _egress_allow_is_narrow(self) -> Self:
        """No allow-list entry wider than /8 or /16, nor loopback outside dev and test (ADR-043 §8).

        Refused when the settings load, so a misconfigured installation never starts with every
        private range open (lane B's review).
        """
        loopback = (ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("::1/128"))
        for entry in self.egress_allow:
            try:
                network = ipaddress.ip_network(entry.strip(), strict=False)
            except ValueError:
                continue  # a host name
            widest = 8 if network.version == 4 else 16  # noqa: PLR2004 - the rule's prefixes
            if network.prefixlen < widest:
                msg = f"SUPPORTX_EGRESS_ALLOW: {entry} is wider than /{widest}"
                raise ValueError(msg)
            on_loopback = any(network.overlaps(n) for n in loopback if n.version == network.version)
            if on_loopback and self.profile == "production":
                msg = f"SUPPORTX_EGRESS_ALLOW: {entry} opens loopback (dev and test only)"
                raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _valkey_tls_needs_a_tls_url(self) -> Self:
        """A CA with a plaintext URL would look protected and be in clear: refused at start."""
        if self.valkey_tls_ca_file is not None and self.valkey_url is not None:
            scheme = urlsplit(self.valkey_url.get_secret_value()).scheme
            if scheme not in {"valkeys", "rediss"}:
                msg = "SUPPORTX_VALKEY_TLS_CA_FILE needs a valkeys:// SUPPORTX_VALKEY_URL"
                raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _nats_tls_needs_a_tls_url(self) -> Self:
        """As for Valkey: a CA with a nats:// URL would look protected and be in clear."""
        url = self.nats_url
        plaintext = url is not None and urlsplit(url.get_secret_value()).scheme != "tls"
        if self.nats_tls_ca_file is not None and plaintext:
            msg = "SUPPORTX_NATS_TLS_CA_FILE needs a tls:// SUPPORTX_NATS_URL"
            raise ValueError(msg)
        return self

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
                "centrifugo_api_url",
                "centrifugo_api_key",
                "centrifugo_token_secret",
                "api_key_secret",  # its own key, never the session secret (audit row 26)
            )
            missing = [name for name in required if getattr(self, name) is None]
            if self.session_secret is None and self.session_keys is None:
                missing.append("session_secret")  # or SUPPORTX_SESSION_KEYS (D-162)
            if missing:
                names = ", ".join(f"SUPPORTX_{m.upper()}" for m in missing)
                msg = f"production profile requires: {names}"
                raise ValueError(msg)
            if self.session_cookie_secure is False:
                msg = "SUPPORTX_SESSION_COOKIE_SECURE cannot be false in production"
                raise ValueError(msg)
            if (
                self.session_secret is not None
                and len(self.session_secret.get_secret_value()) < SESSION_KEY_MIN_LENGTH
            ):
                msg = "SUPPORTX_SESSION_SECRET must be at least 32 characters in production"
                raise ValueError(msg)
            if (
                self.api_key_secret is not None
                and len(self.api_key_secret.get_secret_value()) < SESSION_KEY_MIN_LENGTH
            ):
                msg = "SUPPORTX_API_KEY_SECRET must be at least 32 characters in production"
                raise ValueError(msg)
            if urlsplit(self.mobile_redirect_uri).scheme != "https":
                # see ADR-044 item 3: a mis-set chart value would send every hand-off code in
                # clear text, and Universal Link / App Link verification needs https anyway.
                msg = (
                    "SUPPORTX_MOBILE_REDIRECT_URI must be https in production (ADR-044 item 3), "
                    f"not {self.mobile_redirect_uri!r}"
                )
                raise ValueError(msg)
            self._production_session_keys()
        if self.entitlement_provider == "licence_file" and self.licence_file is None:
            msg = "SUPPORTX_ENTITLEMENT_PROVIDER=licence_file requires SUPPORTX_LICENCE_FILE"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _session_keys_are_well_formed(self) -> Self:
        self.session_key_entries()  # raises ValueError on a malformed SUPPORTX_SESSION_KEYS
        return self

    def _production_session_keys(self) -> None:
        """D-162: production refuses a ring that would silently end API keys and more."""
        for key_id, secret in self.session_key_entries():
            if len(secret) < SESSION_KEY_MIN_LENGTH:
                msg = (
                    f"SUPPORTX_SESSION_KEYS: the secret of key {key_id!r} must be at least 32 "
                    "characters in production"
                )
                raise ValueError(msg)
        if self.session_keys is None or self.session_secret is not None:
            return
        # Without SUPPORTX_SESSION_SECRET these fall back to nothing: list cursors would differ
        # per replica and domain proofs would fail. SUPPORTX_API_KEY_SECRET is required in
        # production on its own (audit row 26); API keys not yet moved to it stop working once
        # SUPPORTX_SESSION_SECRET goes.
        needed = {
            "SUPPORTX_CURSOR_SECRET": self.cursor_secret,
            "SUPPORTX_DOMAIN_PROOF_SECRET": self.domain_proof_secret,
        }
        missing = [name for name, value in needed.items() if value is None]
        if missing:
            msg = (
                "session_keys_need_legacy_secret: SUPPORTX_SESSION_KEYS is set without "
                "SUPPORTX_SESSION_SECRET, so production also needs "
                f"{', '.join(missing)}. Keep SUPPORTX_SESSION_SECRET set (it no longer seals "
                "sessions once 'legacy' leaves the ring), or set these "
                "(docs/guides/rotating-the-sign-in-key.md, upgrade notes)"
            )
            raise ValueError(msg)

    def session_key_entries(self) -> tuple[tuple[str, str], ...]:
        """The session key ring as (key ID, secret) pairs, newest first; () when not configured.

        Raises ValueError for a malformed SUPPORTX_SESSION_KEYS. Messages name key IDs only,
        never a secret.
        """
        legacy = self.session_secret.get_secret_value() if self.session_secret else None
        if self.session_keys is None:
            return ((LEGACY_SESSION_KEY_ID, legacy),) if legacy else ()
        try:
            listed = json.loads(self.session_keys.get_secret_value())
        except json.JSONDecodeError:
            # `from None`: the decoder's error holds the text, which holds the secrets.
            msg = 'SUPPORTX_SESSION_KEYS must be JSON: a list of {"id": ..., "secret": ...}'
            raise ValueError(msg) from None
        if not isinstance(listed, list) or not listed:
            msg = "SUPPORTX_SESSION_KEYS must be a non-empty list, newest key first"
            raise ValueError(msg)
        entries = [_session_key_entry(item, legacy) for item in listed]
        ids = [key_id for key_id, _ in entries]
        if len(set(ids)) != len(ids):
            msg = "SUPPORTX_SESSION_KEYS: every key ID must be unique"
            raise ValueError(msg)
        return tuple(entries)

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
            and (self.session_secret is not None or self.session_keys is not None)
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


def _session_key_entry(item: object, legacy: str | None) -> tuple[str, str]:
    """One SUPPORTX_SESSION_KEYS item as (ID, secret); {"id": "legacy"} takes SESSION_SECRET."""
    if not isinstance(item, dict) or not set(item) <= {"id", "secret"}:
        msg = 'SUPPORTX_SESSION_KEYS: each key is {"id": ..., "secret": ...} and nothing else'
        raise ValueError(msg)
    key_id = item.get("id")
    if not isinstance(key_id, str) or not SESSION_KEY_ID_PATTERN.fullmatch(key_id):
        msg = "SUPPORTX_SESSION_KEYS: key IDs are 1 to 32 of a-z, 0-9, '_' and '-'"
        raise ValueError(msg)
    secret = item.get("secret")
    if secret is None and key_id == LEGACY_SESSION_KEY_ID and legacy:
        return key_id, legacy
    if not isinstance(secret, str) or not secret:
        msg = f"SUPPORTX_SESSION_KEYS: key {key_id!r} needs a secret"
        raise ValueError(msg)
    if key_id != LEGACY_SESSION_KEY_ID and len(secret.encode()) < SESSION_KEY_MIN_BYTES:
        msg = f"SUPPORTX_SESSION_KEYS: the secret of key {key_id!r} needs at least 32 bytes"
        raise ValueError(msg)
    if key_id == LEGACY_SESSION_KEY_ID and legacy is not None and secret != legacy:
        msg = (
            "SUPPORTX_SESSION_KEYS: key 'legacy' must be SUPPORTX_SESSION_SECRET's secret "
            '(list it as {"id": "legacy"})'
        )
        raise ValueError(msg)
    return key_id, secret


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, validated once at startup."""
    return Settings()
