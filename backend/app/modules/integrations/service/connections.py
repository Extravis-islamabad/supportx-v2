"""How a mailbox is reached: IMAP, Microsoft Graph or the Gmail API (WP-024; REQ-INT-050).

Secrets are sealed with the installation key ring, bound to the tenant and a purpose
(`mailbox` for the IMAP password or the OAuth app's secret or certificate, `mailbox_token` for a
refresh token, `mailbox_consent` for a consent in progress), and never returned or logged.

Consent (Gmail, and Graph with delegated permission): an admin starts it on Admin > Mail, signs
in as the mailbox at Microsoft or Google, and comes back to `/api/v1/integrations/oauth/callback`
on the same address. The state is random, stored only as a hash, valid for ten minutes and for the
admin who started it; PKCE binds the code to this installation. The account that signed in must be
the mailbox itself, so a refresh token never reads someone else's mail.
"""

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.integrations.domain.mailboxes import (
    AuthModel,
    ConnectionSecurity,
    CredentialKind,
    MailboxProtocol,
    MailboxState,
    needs_sign_in,
    scopes_for,
)
from app.modules.integrations.infra.imap import (
    ImapReader,
    ImapSettings,
    MailboxReader,
    MailboxUnavailableError,
)
from app.modules.integrations.infra.mail_apis import GmailReader, GraphReader, account_address
from app.modules.integrations.infra.models import Mailbox
from app.modules.integrations.infra.oauth import (
    OAUTH_NOT_CONNECTED,
    OAUTH_WRONG_ACCOUNT,
    Client,
    Endpoints,
    OAuth,
    load_certificate,
    pkce_pair,
)
from app.shared.files.keyring import KeyRing, KeyRingError

SECRET_PURPOSE = "mailbox"  # noqa: S105 - the sealing context, not a password
TOKEN_PURPOSE = "mailbox_token"  # noqa: S105 - the sealing context
CONSENT_PURPOSE = "mailbox_consent"
NOT_SET = "mailbox_no_password"
UNREADABLE = "mailbox_secret_unreadable"
CALLBACK_PATH = "/api/v1/integrations/oauth/callback"
CONSENT_TTL = timedelta(minutes=10)
# Consent refusals, shown on Admin > Mail after the callback (labels "mailbox.reason.<code>").
CONSENT_EXPIRED = "oauth_consent_expired"
CONSENT_NOT_YOURS = "oauth_consent_not_yours"
CONSENT_DECLINED = "oauth_consent_declined"

_TRANSPORT: list[httpx.AsyncBaseTransport] = []


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Tests: send every provider call to a fake Microsoft or Google (None: the real ones)."""
    _TRANSPORT.clear()
    if transport is not None:
        _TRANSPORT.append(transport)


def oauth_for(settings: Settings) -> OAuth:
    """The OAuth client for this installation's provider endpoints."""
    endpoints = Endpoints(
        microsoft_login=settings.mail_microsoft_login_url.rstrip("/"),
        graph=settings.mail_graph_url.rstrip("/"),
        google_authorize=settings.mail_google_authorize_url,
        google_token=settings.mail_google_token_url,
        gmail=settings.mail_gmail_url.rstrip("/"),
    )
    return OAuth(endpoints, _TRANSPORT[0] if _TRANSPORT else None)


def key_ring(settings: Settings) -> KeyRing | None:
    """The installation key ring (the same as for files), or None when not configured."""
    if settings.files_keys is None:
        return None
    return KeyRing.parse(settings.files_keys.get_secret_value())


def seal(ring: KeyRing, tenant_id: uuid.UUID, purpose: str, value: str) -> tuple[str, bytes]:
    """(key id, sealed bytes) to store; the value is never stored in clear."""
    return ring.seal(tenant_id, purpose, value.encode())


def _unseal(ring: KeyRing, tenant_id: uuid.UUID, purpose: str, key_id: str, sealed: bytes) -> str:
    try:
        return ring.unseal(tenant_id, purpose, key_id, sealed).decode()
    except KeyRingError as exc:
        raise MailboxUnavailableError(UNREADABLE) from exc


def stored_secret(mailbox: Mailbox, ring: KeyRing) -> str:
    """The IMAP password or the OAuth app's credential (MailboxUnavailableError when none)."""
    if mailbox.secret_key_id is None or mailbox.secret_sealed is None:
        raise MailboxUnavailableError(NOT_SET)
    return _unseal(
        ring, mailbox.tenant_id, SECRET_PURPOSE, mailbox.secret_key_id, mailbox.secret_sealed
    )


def credential_expiry(kind: CredentialKind, credential: str) -> datetime | None:
    """When a certificate stops working (read from it); a secret's expiry is the admin's input."""
    if kind is CredentialKind.CERTIFICATE:
        return load_certificate(credential).expires_at
    return None


def client_of(mailbox: Mailbox, ring: KeyRing, secret: str | None = None) -> Client:
    """The customer's OAuth app as this mailbox uses it."""
    return Client(
        protocol=MailboxProtocol(mailbox.protocol),
        client_id=mailbox.client_id or "",
        credential_kind=CredentialKind(mailbox.credential_kind or CredentialKind.SECRET),
        credential=secret if secret is not None else stored_secret(mailbox, ring),
        directory_id=mailbox.directory_id,
    )


@dataclass(frozen=True)
class Opened:
    """A reader, and a new refresh token to store when the provider rotated it."""

    reader: MailboxReader
    new_refresh_token: str | None = None


async def open_reader(
    mailbox: Mailbox, ring: KeyRing, settings: Settings, *, secret: str | None = None
) -> Opened:
    """A reader for the mailbox; `secret` tries a new password or credential before saving it."""
    protocol = MailboxProtocol(mailbox.protocol)
    if protocol is MailboxProtocol.IMAP:
        return Opened(
            ImapReader(
                ImapSettings(
                    host=mailbox.host or "",
                    port=mailbox.port or 993,
                    security=ConnectionSecurity(mailbox.security),
                    username=mailbox.username or "",
                    password=secret if secret is not None else stored_secret(mailbox, ring),
                    folder=mailbox.folder,
                )
            )
        )
    oauth = oauth_for(settings)
    client = client_of(mailbox, ring, secret)
    auth_model = AuthModel(mailbox.auth_model or AuthModel.DELEGATED)
    scopes = scopes_for(protocol, auth_model)
    rotated: str | None = None
    if auth_model is AuthModel.APP:
        access = (await oauth.app_token(client, scopes)).access_token
    else:
        if mailbox.token_key_id is None or mailbox.token_sealed is None:
            raise MailboxUnavailableError(OAUTH_NOT_CONNECTED)
        refresh = _unseal(
            ring, mailbox.tenant_id, TOKEN_PURPOSE, mailbox.token_key_id, mailbox.token_sealed
        )
        tokens = await oauth.refresh(client, refresh, scopes)
        access = tokens.access_token
        if tokens.refresh_token and tokens.refresh_token != refresh:
            rotated = tokens.refresh_token  # Microsoft rotates them: keep the newest
    if protocol is MailboxProtocol.GMAIL:
        reader: MailboxReader = GmailReader(
            oauth.http(), oauth.endpoints.gmail, access, folder=mailbox.folder
        )
    else:
        reader = GraphReader(
            oauth.http(),
            oauth.endpoints.graph,
            access,
            address=mailbox.address if auth_model is AuthModel.APP else None,
            folder=mailbox.folder,
        )
    return Opened(reader, rotated)


def store_refresh_token(mailbox: Mailbox, ring: KeyRing, token: str) -> None:
    """Keep a (rotated) refresh token, sealed."""
    mailbox.token_key_id, mailbox.token_sealed = seal(ring, mailbox.tenant_id, TOKEN_PURPOSE, token)


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


class ConsentRefusedError(Exception):
    """The consent could not start or finish; `reason` is a label code for Admin > Mail."""

    def __init__(self, reason: str, mailbox_id: uuid.UUID | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.mailbox_id = mailbox_id


def start_consent(
    mailbox: Mailbox, ring: KeyRing, settings: Settings, *, admin_id: uuid.UUID, origin: str
) -> str:
    """The provider's sign-in address; the mailbox remembers the consent for ten minutes."""
    protocol = MailboxProtocol(mailbox.protocol)
    auth_model = AuthModel(mailbox.auth_model) if mailbox.auth_model else None
    if not needs_sign_in(protocol, auth_model):
        reason = "mailbox_sign_in_not_needed"
        raise ConsentRefusedError(reason, mailbox.id)
    client = client_of(mailbox, ring)
    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    redirect_uri = origin.rstrip("/") + CALLBACK_PATH
    pending = json.dumps(
        {"verifier": verifier, "redirect_uri": redirect_uri, "admin_id": str(admin_id)}
    )
    mailbox.oauth_state_hash = _hash(state)
    mailbox.oauth_pending_key_id, mailbox.oauth_pending_sealed = seal(
        ring, mailbox.tenant_id, CONSENT_PURPOSE, pending
    )
    mailbox.oauth_pending_until = datetime.now(UTC) + CONSENT_TTL
    return oauth_for(settings).authorize_url(
        client,
        redirect_uri=redirect_uri,
        scopes=scopes_for(protocol, auth_model or AuthModel.DELEGATED),
        state=state,
        code_challenge=challenge,
        login_hint=mailbox.address,
    )


async def pending_consent(session: AsyncSession, state: str) -> Mailbox | None:
    """The mailbox whose consent this state belongs to (in the session's tenant), if any."""
    return await session.scalar(
        select(Mailbox).where(
            Mailbox.oauth_state_hash == _hash(state), Mailbox.deleted_at.is_(None)
        )
    )


async def finish_consent(  # noqa: PLR0913 - the callback's facts, explicit
    mailbox: Mailbox,
    ring: KeyRing,
    settings: Settings,
    *,
    code: str,
    admin_id: uuid.UUID,
    origin: str,
) -> None:
    """Exchange the code, check the account, keep the refresh token sealed (the caller commits)."""
    sealed_key, sealed = mailbox.oauth_pending_key_id, mailbox.oauth_pending_sealed
    until = mailbox.oauth_pending_until
    # Used once: cleared whatever happens next.
    mailbox.oauth_state_hash = mailbox.oauth_pending_key_id = None
    mailbox.oauth_pending_sealed = mailbox.oauth_pending_until = None
    if sealed_key is None or sealed is None or until is None or until < datetime.now(UTC):
        raise ConsentRefusedError(CONSENT_EXPIRED, mailbox.id)
    try:
        pending = json.loads(_unseal(ring, mailbox.tenant_id, CONSENT_PURPOSE, sealed_key, sealed))
    except MailboxUnavailableError as exc:
        raise ConsentRefusedError(exc.reason, mailbox.id) from exc
    redirect_uri = str(pending["redirect_uri"])
    if pending["admin_id"] != str(admin_id) or redirect_uri != origin.rstrip("/") + CALLBACK_PATH:
        raise ConsentRefusedError(CONSENT_NOT_YOURS, mailbox.id)
    oauth = oauth_for(settings)
    try:
        tokens = await oauth.exchange(
            client_of(mailbox, ring),
            code=code,
            redirect_uri=redirect_uri,
            verifier=str(pending["verifier"]),
        )
        protocol = MailboxProtocol(mailbox.protocol)
        async with oauth.http() as http:
            account = await account_address(
                http,
                graph_url=oauth.endpoints.graph if protocol is MailboxProtocol.GRAPH else None,
                gmail_url=oauth.endpoints.gmail if protocol is MailboxProtocol.GMAIL else None,
                access_token=tokens.access_token,
            )
    except MailboxUnavailableError as exc:
        raise ConsentRefusedError(exc.reason, mailbox.id) from exc
    if not tokens.refresh_token:  # no offline access granted: it could not stay connected
        raise ConsentRefusedError(OAUTH_NOT_CONNECTED, mailbox.id)
    if account != mailbox.address.lower():
        raise ConsentRefusedError(OAUTH_WRONG_ACCOUNT, mailbox.id)
    store_refresh_token(mailbox, ring, tokens.refresh_token)
    mailbox.connected_account = account
    # Read at the next poll; the state shows "not checked yet" until then.
    mailbox.state, mailbox.state_reason = MailboxState.NOT_SET_UP.value, None
    mailbox.next_fetch_at = None
