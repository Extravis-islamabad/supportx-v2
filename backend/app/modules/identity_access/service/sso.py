"""Single sign-on set-ups of a tenant (WP-039; REQ-SEC-007, REQ-SEC-008; ADR-033, D-094).

Life cycle: **draft** (saved: Keycloak has the provider, hidden, linked to the tenant's
organization) → **tested** (an admin signed in through it, service/sso_test.py) → **on** (on the
tenant's sign-in page) ⇄ **off** (disabled in Keycloak, kept here). Changing how SupportX
connects (issuer, client, metadata) sends a set-up back to draft, so it is tested again before
anyone depends on it; an "on" set-up must be switched off first, so a typo never locks a whole
tenant out. Removing deletes the Keycloak provider.

Saving checks the connection where it can (REQ-SEC-007 AC1, a plain reason): OIDC fetches the
discovery document (its issuer must be the one typed) and, when a secret is given, asks the
provider whether it accepts the client; SAML reads the metadata with Keycloak's own parser
(D-089) and checks the signing certificate's dates. The client secret goes to Keycloak only and
never comes back (REQ-SEC-042).

Email domains: the set-up's domains become the organization's domains in Keycloak, routed to its
provider (a domain belongs to one organization only, so another tenant's domain is refused; two
set-ups of a tenant never share one), with people sent straight there only while it is on and
when chosen. SupportX removes only the domains it added.

The Keycloak calls are not in the database transaction: Keycloak is changed first and the row
last, and a failed row write undoes a provider just created.
"""

import json
import secrets
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from cryptography import x509
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.modules.identity_access.domain import sso
from app.modules.identity_access.events import SsoProviderChanged
from app.modules.identity_access.infra.fetch import FetchError, client_accepted, fetch_document
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdmin,
    IdentityAdminNotConfigured,
    IdentityAdminRefused,
    Organization,
)
from app.modules.identity_access.infra.models import SsoProvider
from app.modules.organization import get_current_tenant
from app.shared.events import record_event
from app.shared.ids import new_id

# Settings that decide how SupportX connects: a change sends the set-up back to draft.
CONNECTION_KEYS = ("issuer", "client_id", "scopes", "sso_url", "certificate", "entity_id")


@dataclass(frozen=True)
class SsoInput:
    """What an admin enters (secret and SAML metadata are write-only, never stored here)."""

    preset: sso.Preset
    display_name: str
    domains: list[str]
    email_redirect: bool = False
    mapping: sso.Mapping | None = None
    # OIDC
    issuer: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scopes: str = sso.DEFAULT_SCOPES
    # SAML: metadata (uploaded or from a URL), or the fields by hand.
    metadata: str | None = None
    metadata_url: str | None = None
    sso_url: str | None = None
    slo_url: str | None = None
    certificate: str | None = None
    entity_id: str | None = None

    @property
    def protocol(self) -> sso.Protocol:
        """SAML for the SAML preset, OpenID Connect otherwise."""
        return "saml" if self.preset == "saml" else "oidc"


@dataclass(frozen=True)
class CheckResult:
    """The connection check: `ok`, or the problem codes (`sso_check.<code>`)."""

    ok: bool
    problems: list[str]
    checked_at: str
    certificate_not_after: str | None = None


@dataclass
class SsoView:
    """A set-up as the admin screen shows it (never the secret)."""

    id: uuid.UUID
    alias: str
    protocol: str
    preset: str
    display_name: str
    state: str
    domains: list[str]
    email_redirect: bool
    settings: dict[str, Any]
    last_check: dict[str, Any] | None
    tested_at: datetime | None
    switched_on_at: datetime | None
    version: int
    service_provider_metadata_path: str = field(default="")


def _view(row: SsoProvider) -> SsoView:
    public = {k: v for k, v in row.settings.items() if k != "added_domains"}
    return SsoView(
        id=row.id,
        alias=row.alias,
        protocol=row.protocol,
        preset=row.preset,
        display_name=row.display_name,
        state=row.state,
        domains=list(row.domains),
        email_redirect=row.email_redirect,
        settings=public,
        last_check=row.last_check,
        tested_at=row.tested_at,
        switched_on_at=row.switched_on_at,
        version=row.version,
        # Keycloak's service provider metadata for this set-up (SAML: give it to the provider).
        service_provider_metadata_path=f"/broker/{row.alias}/endpoint/descriptor",
    )


def _invalid(problems: list[sso.Problem]) -> ValidationFailed:
    return ValidationFailed(
        errors=[
            FieldError(
                field=p.field, code=p.code, message_key=f"errors.field.{p.code}", params=p.params
            )
            for p in problems
        ]
    )


def _require(admin: IdentityAdmin | None) -> IdentityAdmin:
    if admin is None:
        raise IdentityAdminNotConfigured
    return admin


def _check_ownership(organization: Organization, domains: list[str], *, required: bool) -> None:
    """Multi-tenant installations route only domains whose ownership was proved (D-098).

    In a realm tenants share, routing an unproved domain would let a tenant claim another
    company's domain and send its people to its own provider. The proof (DNS TXT) comes with the
    SaaS cell (WP-014d) and marks the organization's domain verified; until then nothing can be
    routed there. Single-tenant installations (one organization per realm) are not affected.
    """
    if not required:
        return
    verified = {d["name"] for d in organization.raw.get("domains") or [] if d.get("verified")}
    unproved = [d for d in domains if d not in verified]
    if unproved:
        raise _invalid([sso.Problem("domains", "sso_domain_unverified", {"domain": unproved[0]})])


async def _organization(session: AsyncSession, admin: IdentityAdmin) -> Organization:
    tenant = await get_current_tenant(session)
    found = await admin.organization(tenant.slug, str(tenant.id))
    if found is None:
        raise Conflict(code="identity_organization_missing")
    return found


async def list_providers(session: AsyncSession) -> list[SsoView]:
    """The tenant's set-ups, oldest first."""
    rows = await session.scalars(
        select(SsoProvider).where(SsoProvider.deleted_at.is_(None)).order_by(SsoProvider.created_at)
    )
    return [_view(row) for row in rows]


async def _row(session: AsyncSession, provider_id: uuid.UUID) -> SsoProvider:
    row = await session.scalar(
        select(SsoProvider)
        .where(SsoProvider.id == provider_id, SsoProvider.deleted_at.is_(None))
        .with_for_update()
    )
    if row is None:
        raise NotFound(code="sso_provider_not_found")
    return row


def _check_version(row: SsoProvider, expected: int) -> None:
    if row.version != expected:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected, "current_version": row.version},
        )


def _validate(values: SsoInput, *, creating: bool) -> tuple[list[str], list[sso.Problem]]:
    domains, problems = sso.normalise_domains(values.domains)
    name = values.display_name.strip()
    if not 1 <= len(name) <= 80:  # noqa: PLR2004 - the column's length
        problems.append(sso.Problem("display_name", "sso_name_length", {"max": 80}))
    if values.protocol == "oidc":
        problems += _validate_oidc(values, creating=creating)
    else:
        problems += _validate_saml(values)
    return domains, problems


def _validate_oidc(values: SsoInput, *, creating: bool) -> list[sso.Problem]:
    problems: list[sso.Problem] = []
    if not values.issuer:
        problems.append(sso.Problem("issuer", "sso_issuer_required"))
    elif (bad := sso.check_url(values.issuer, "issuer")) is not None:
        problems.append(bad)
    if not values.client_id or not values.client_id.strip():
        problems.append(sso.Problem("client_id", "sso_client_id_required"))
    if creating and not values.client_secret:
        problems.append(sso.Problem("client_secret", "sso_client_secret_required"))
    return problems


def _validate_saml(values: SsoInput) -> list[sso.Problem]:
    problems: list[sso.Problem] = []
    has_metadata = bool(values.metadata or values.metadata_url)
    if not (has_metadata or values.sso_url):
        problems.append(sso.Problem("metadata", "sso_metadata_required"))
    for name, url in (("metadata_url", values.metadata_url), ("sso_url", values.sso_url)):
        if url and (bad := sso.check_url(url, name)) is not None:
            problems.append(bad)
    if values.sso_url and not has_metadata and not values.certificate:
        problems.append(sso.Problem("certificate", "sso_certificate_required"))
    return problems


def _certificate_dates(pem_or_base64: str) -> tuple[datetime, datetime] | None:
    text = pem_or_base64.strip()
    if "BEGIN CERTIFICATE" not in text:
        text = f"-----BEGIN CERTIFICATE-----\n{text}\n-----END CERTIFICATE-----"
    try:
        certificate = x509.load_pem_x509_certificate(text.encode())
    except ValueError:
        return None
    return certificate.not_valid_before_utc, certificate.not_valid_after_utc


def _json_object(text: str) -> dict[str, Any] | None:
    try:
        found = json.loads(text)
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


async def _connect_oidc(
    values: SsoInput, *, allow_loopback: bool
) -> tuple[dict[str, str], list[str]]:
    """Keycloak settings from the discovery document, and the check's problems."""
    issuer = (values.issuer or "").rstrip("/")
    problems: list[str] = []
    try:
        text = await fetch_document(
            f"{issuer}/.well-known/openid-configuration", allow_loopback=allow_loopback
        )
    except FetchError:
        raise _invalid([sso.Problem("issuer", "sso_discovery_unreachable")]) from None
    discovery = _json_object(text)
    if discovery is None or "authorization_endpoint" not in discovery:
        raise _invalid([sso.Problem("issuer", "sso_discovery_invalid")])
    if not sso.issuer_matches(issuer, str(discovery.get("issuer", ""))):
        raise _invalid([sso.Problem("issuer", "sso_issuer_mismatch")])
    config = sso.oidc_config(
        discovery,
        client_id=(values.client_id or "").strip(),
        scopes=values.scopes,
    )
    if not issuer.startswith("https://"):
        problems.append("not_https")
    if values.client_secret:
        try:
            accepted = await client_accepted(
                config["tokenUrl"],
                config["clientId"],
                values.client_secret,
                allow_loopback=allow_loopback,
            )
        except FetchError:
            accepted = True  # the token endpoint was not reachable: the test sign-in will tell
        if not accepted:
            raise _invalid([sso.Problem("client_secret", "sso_client_rejected")])
    return config, problems


async def _connect_saml(
    values: SsoInput, admin: IdentityAdmin, *, allow_loopback: bool
) -> tuple[dict[str, str], list[str], str | None]:
    """Keycloak settings from the metadata (or the fields), the problems and the cert's end."""
    parsed: dict[str, str]
    if values.metadata or values.metadata_url:
        metadata = values.metadata
        if metadata is None:
            try:
                metadata = await fetch_document(
                    values.metadata_url or "", allow_loopback=allow_loopback
                )
            except FetchError:
                raise _invalid([sso.Problem("metadata_url", "sso_metadata_unreachable")]) from None
        try:
            parsed = await admin.parse_saml_metadata(metadata)
        except IdentityAdminRefused:
            raise _invalid([sso.Problem("metadata", "sso_metadata_unreadable")]) from None
    else:
        parsed = {
            "singleSignOnServiceUrl": values.sso_url or "",
            "singleLogoutServiceUrl": values.slo_url or "",
            "signingCertificate": (values.certificate or "")
            .replace("-----BEGIN CERTIFICATE-----", "")
            .replace("-----END CERTIFICATE-----", "")
            .replace("\n", "")
            .strip(),
            "idpEntityId": values.entity_id or "",
            "postBindingResponse": "true",
        }
    if not parsed.get("singleSignOnServiceUrl"):
        raise _invalid([sso.Problem("metadata", "sso_sign_in_url_missing")])
    certificate = (parsed.get("signingCertificate") or "").split(",")[0]
    if not certificate:
        raise _invalid([sso.Problem("certificate", "sso_certificate_missing")])
    dates = _certificate_dates(certificate)
    if dates is None:
        raise _invalid([sso.Problem("certificate", "sso_certificate_unreadable")])
    now = datetime.now(UTC)
    if dates[1] <= now:
        raise _invalid([sso.Problem("certificate", "sso_certificate_expired")])
    problems = [] if dates[0] <= now else ["certificate_not_yet_valid"]
    if not parsed["singleSignOnServiceUrl"].startswith("https://"):
        problems.append("not_https")
    config = sso.saml_config(parsed)
    return config, problems, dates[1].isoformat()


def _public_settings(values: SsoInput, config: dict[str, str]) -> dict[str, Any]:
    """What the screen shows again (never the secret or the metadata itself)."""
    mapping = values.mapping or (
        sso.SAML_MAPPING if values.protocol == "saml" else sso.OIDC_MAPPING
    )
    found: dict[str, Any] = {"mapping": asdict(mapping)}
    if values.protocol == "oidc":
        found |= {
            "issuer": (values.issuer or "").rstrip("/"),
            "client_id": config.get("clientId"),
            "scopes": values.scopes or sso.DEFAULT_SCOPES,
        }
    else:
        found |= {
            "sso_url": config.get("singleSignOnServiceUrl"),
            "slo_url": config.get("singleLogoutServiceUrl") or None,
            "entity_id": config.get("idpEntityId") or None,
            "certificate": config.get("signingCertificate", "")[:64],
        }
    return found


async def _set_domains(  # noqa: PLR0913 - the organization and the set-up's routing, explicit
    admin: IdentityAdmin,
    organization: Organization,
    *,
    alias: str,
    mine: list[str],
    drop: set[str],
    redirect: bool,
) -> list[str]:
    """Route `mine` to the set-up's provider, give back `drop`; returns the domains newly added.

    `drop` holds only domains SupportX added and no other set-up uses; the organization's other
    domains stay as they are. A domain another organization has is refused (Keycloak).
    """
    current = list(organization.raw.get("domains") or [])
    routed = sso.route_domains(current, alias=alias, mine=mine, drop=drop, redirect=redirect)
    if routed != current:
        try:
            await admin.set_organization_domains(organization, routed)
        except IdentityAdminRefused as exc:
            raise _invalid([sso.Problem("domains", "sso_domain_taken")]) from exc
    known = {d["name"] for d in current}
    return [d for d in mine if d not in known]


async def _check_overlap(
    session: AsyncSession, domains: list[str], provider_id: uuid.UUID | None
) -> None:
    """Two of a tenant's set-ups never share a domain (it can be routed to one only)."""
    others = await _domains_of_others(session, provider_id)
    shared = [d for d in domains if d in others]
    if shared:
        raise _invalid([sso.Problem("domains", "sso_domain_in_use", {"domain": shared[0]})])


async def _changed(session: AsyncSession, row: SsoProvider, change: str) -> None:
    await record_event(
        session,
        SsoProviderChanged(change=change, state=row.state),  # type: ignore[arg-type]  # change and state are checked literals of the model's columns
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def create_provider(
    session: AsyncSession,
    admin: IdentityAdmin | None,
    values: SsoInput,
    *,
    allow_loopback: bool = False,
    require_domain_proof: bool = False,
) -> SsoView:
    """A new set-up in draft (Keycloak: hidden, linked, its mappers and domains)."""
    keycloak = _require(admin)
    domains, problems = _validate(values, creating=True)
    if problems:
        raise _invalid(problems)
    count = await session.scalar(
        select(func.count()).select_from(SsoProvider).where(SsoProvider.deleted_at.is_(None))
    )
    if (count or 0) >= sso.MAX_PROVIDERS:
        raise Conflict(code="sso_provider_limit", params={"max": sso.MAX_PROVIDERS})
    await _check_overlap(session, domains, None)
    organization = await _organization(session, keycloak)
    _check_ownership(organization, domains, required=require_domain_proof)
    if values.protocol == "oidc":
        config, warnings = await _connect_oidc(values, allow_loopback=allow_loopback)
        not_after = None
    else:
        config, warnings, not_after = await _connect_saml(
            values, keycloak, allow_loopback=allow_loopback
        )
    tenant = await get_current_tenant(session)
    alias = sso.alias_for(tenant.slug, secrets.token_hex(3))
    representation = sso.representation(
        alias=alias,
        protocol=values.protocol,
        display_name=values.display_name.strip(),
        config=config,
        state="draft",
        client_secret=values.client_secret,
    )
    mapping = values.mapping or (
        sso.SAML_MAPPING if values.protocol == "saml" else sso.OIDC_MAPPING
    )
    try:
        await keycloak.create_provider(representation)
    except IdentityAdminRefused as exc:
        raise Conflict(code="sso_provider_refused") from exc
    try:
        await keycloak.link_provider(organization.id, alias)
        await keycloak.replace_mappers(alias, sso.mappers(values.protocol, mapping))
        added = await _set_domains(
            keycloak, organization, alias=alias, mine=domains, drop=set(), redirect=False
        )
        context = session.info[SESSION_TENANT_KEY]
        row = SsoProvider(
            id=new_id(),
            tenant_id=context.tenant_id,
            alias=alias,
            protocol=values.protocol,
            preset=values.preset,
            display_name=values.display_name.strip(),
            state="draft",
            settings=_public_settings(values, config) | {"added_domains": added},
            domains=domains,
            email_redirect=values.email_redirect,
            last_check=asdict(
                CheckResult(
                    ok=not warnings,
                    problems=warnings,
                    checked_at=datetime.now(UTC).isoformat(),
                    certificate_not_after=not_after,
                )
            ),
            version=1,
        )
        session.add(row)
        await session.flush()
    except Exception:
        await keycloak.delete_provider(alias)  # never leave a provider SupportX does not know
        raise
    await _changed(session, row, "added")
    return _view(row)


async def update_provider(  # noqa: PLR0913 - the record, its input and version, keyword-only rest
    session: AsyncSession,
    admin: IdentityAdmin | None,
    provider_id: uuid.UUID,
    values: SsoInput,
    *,
    expected_version: int,
    allow_loopback: bool = False,
    require_domain_proof: bool = False,
) -> SsoView:
    """Change a set-up; a connection change sends it back to draft (switch it off first)."""
    keycloak = _require(admin)
    row = await _row(session, provider_id)
    _check_version(row, expected_version)
    if values.protocol != row.protocol:
        raise _invalid([sso.Problem("preset", "sso_protocol_fixed")])
    domains, problems = _validate(values, creating=False)
    if problems:
        raise _invalid(problems)
    await _check_overlap(session, domains, row.id)
    organization = await _organization(session, keycloak)
    _check_ownership(organization, domains, required=require_domain_proof)
    if values.protocol == "oidc":
        config, warnings = await _connect_oidc(values, allow_loopback=allow_loopback)
        not_after = None
    else:
        reuse = not (values.metadata or values.metadata_url or values.sso_url)
        if reuse:
            stored = await keycloak.provider(row.alias)
            config = dict((stored or {}).get("config") or {})
            config |= sso.saml_config(config)
            warnings, not_after = [], (row.last_check or {}).get("certificate_not_after")
        else:
            config, warnings, not_after = await _connect_saml(
                values, keycloak, allow_loopback=allow_loopback
            )
    public = _public_settings(values, config)
    connection_changed = values.client_secret is not None or any(
        public.get(key) != row.settings.get(key) for key in CONNECTION_KEYS if key in public
    )
    if connection_changed and row.state == "on":
        raise Conflict(code="sso_switch_off_first")
    state: sso.State = "draft" if connection_changed else row.state  # type: ignore[assignment]  # the column only holds states
    try:
        await keycloak.update_provider(
            row.alias,
            sso.representation(
                alias=row.alias,
                protocol=values.protocol,
                display_name=values.display_name.strip(),
                config=config,
                state=state,
                client_secret=values.client_secret,
            ),
        )
    except IdentityAdminRefused as exc:
        raise Conflict(code="sso_provider_refused") from exc
    mapping = values.mapping or (
        sso.SAML_MAPPING if values.protocol == "saml" else sso.OIDC_MAPPING
    )
    await keycloak.replace_mappers(row.alias, sso.mappers(values.protocol, mapping))
    ours = set(row.settings.get("added_domains") or [])
    gone = {d for d in ours if d not in domains}
    added = await _set_domains(
        keycloak,
        organization,
        alias=row.alias,
        mine=domains,
        drop=gone,
        redirect=state == "on" and values.email_redirect,
    )
    row.display_name = values.display_name.strip()
    row.domains = domains
    row.email_redirect = values.email_redirect
    row.settings = public | {"added_domains": sorted((ours - gone) | set(added))}
    row.last_check = asdict(
        CheckResult(
            ok=not warnings,
            problems=warnings,
            checked_at=datetime.now(UTC).isoformat(),
            certificate_not_after=not_after,
        )
    )
    if connection_changed:
        row.state = "draft"
        row.tested_at = None
        row.tested_by = None
    row.version += 1
    await session.flush()
    await _changed(session, row, "updated")
    return _view(row)


async def _domains_of_others(session: AsyncSession, provider_id: uuid.UUID | None) -> set[str]:
    query = select(SsoProvider.domains).where(SsoProvider.deleted_at.is_(None))
    if provider_id is not None:
        query = query.where(SsoProvider.id != provider_id)
    rows = await session.scalars(query)
    return {d for domains in rows for d in domains}


async def switch_provider(
    session: AsyncSession,
    admin: IdentityAdmin | None,
    provider_id: uuid.UUID,
    *,
    on: bool,
    expected_version: int,
) -> SsoView:
    """On (needs a passed test since the last connection change) or off."""
    keycloak = _require(admin)
    row = await _row(session, provider_id)
    _check_version(row, expected_version)
    if on and row.tested_at is None:
        raise Conflict(code="sso_not_tested")
    stored = await keycloak.provider(row.alias)
    if stored is None:
        raise Conflict(code="sso_provider_missing")
    state: sso.State = "on" if on else "off"
    stored["enabled"] = state != "off"
    stored["hideOnLogin"] = state != "on"
    await keycloak.update_provider(row.alias, stored)
    # People of the set-up's domains go straight to it only while it is on (and if chosen).
    await _set_domains(
        keycloak,
        await _organization(session, keycloak),
        alias=row.alias,
        mine=list(row.domains),
        drop=set(),
        redirect=on and row.email_redirect,
    )
    row.state = state
    row.switched_on_at = datetime.now(UTC) if on else row.switched_on_at
    row.version += 1
    await session.flush()
    await _changed(session, row, "switched_on" if on else "switched_off")
    return _view(row)


async def remove_provider(
    session: AsyncSession,
    admin: IdentityAdmin | None,
    provider_id: uuid.UUID,
    *,
    expected_version: int,
) -> SsoView:
    """Delete the Keycloak provider, give back the domains only it claimed, keep the row."""
    keycloak = _require(admin)
    row = await _row(session, provider_id)
    _check_version(row, expected_version)
    organization = await _organization(session, keycloak)
    ours = set(row.settings.get("added_domains") or [])
    await keycloak.delete_provider(row.alias)
    await _set_domains(keycloak, organization, alias=row.alias, mine=[], drop=ours, redirect=False)
    row.deleted_at = datetime.now(UTC)
    row.state = "off"
    row.version += 1
    await session.flush()
    await _changed(session, row, "removed")
    return _view(row)


async def mark_tested(session: AsyncSession, provider_id: uuid.UUID, tester: uuid.UUID) -> SsoView:
    """A passed test sign-in: the set-up may be switched on."""
    row = await _row(session, provider_id)
    row.tested_at = datetime.now(UTC)
    row.tested_by = tester
    if row.state == "draft":
        row.state = "tested"
    row.version += 1
    await session.flush()
    await _changed(session, row, "tested")
    return _view(row)


async def test_target(session: AsyncSession, provider_id: uuid.UUID) -> SsoView:
    """The set-up to test: any but one switched off (Keycloak has it disabled)."""
    view = await get_provider(session, provider_id)
    if view.state == "off":
        raise Conflict(code="sso_switched_off")
    return view


async def get_provider(session: AsyncSession, provider_id: uuid.UUID) -> SsoView:
    """One set-up of the tenant."""
    row = await session.scalar(
        select(SsoProvider).where(SsoProvider.id == provider_id, SsoProvider.deleted_at.is_(None))
    )
    if row is None:
        raise NotFound(code="sso_provider_not_found")
    return _view(row)
