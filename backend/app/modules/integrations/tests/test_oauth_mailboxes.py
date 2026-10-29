"""Microsoft 365 and Gmail mailboxes without a database (WP-024 session 2; REQ-INT-050).

Everything runs against `fake_providers`: no real Microsoft or Google account, no network.
"""

import base64
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID
from pydantic import SecretStr

from app.core.config import Settings
from app.modules.integrations.domain.mailboxes import (
    AfterFetch,
    AuthModel,
    CredentialKind,
    MailboxProtocol,
    credential_warning_due,
    oauth_problems,
    scopes_for,
)
from app.modules.integrations.infra.imap import MailboxUnavailableError
from app.modules.integrations.infra.models import Mailbox
from app.modules.integrations.infra.oauth import (
    OAUTH_CERTIFICATE_INVALID,
    OAUTH_CLIENT_REJECTED,
    OAUTH_CONSENT_REVOKED,
    OAUTH_NOT_ALLOWED,
    OAUTH_NOT_CONNECTED,
    OAUTH_WRONG_ACCOUNT,
    load_certificate,
)
from app.modules.integrations.service import connections
from app.modules.integrations.service.connections import (
    CONSENT_EXPIRED,
    CONSENT_NOT_YOURS,
    SECRET_PURPOSE,
    TOKEN_PURPOSE,
    ConsentRefusedError,
    finish_consent,
    open_reader,
    start_consent,
)
from app.modules.integrations.tests.fake_providers import (
    GMAIL,
    GRAPH,
    FakeProviders,
    endpoint_settings,
)
from app.shared.files.keyring import KeyRing
from conftest import make_settings

ADDRESS = "support@acme.test"
ORIGIN = "https://acme.support.test"
TENANT = uuid.uuid4()
ADMIN = uuid.uuid4()
RAW = b"From: sara@acme.test\r\nTo: support@acme.test\r\nSubject: Printer\r\n\r\nIt jams.\r\n"


@pytest.fixture
def fake() -> Iterator[FakeProviders]:
    providers = FakeProviders()
    connections.use_transport(providers.transport())
    yield providers
    connections.use_transport(None)


@pytest.fixture
def ring() -> KeyRing:
    return KeyRing.parse(KeyRing.generate("k1"))


@pytest.fixture
def settings() -> Settings:
    return make_settings(files_keys=SecretStr(KeyRing.generate("k1")), **endpoint_settings())


def _mailbox(
    ring: KeyRing,
    protocol: MailboxProtocol,
    auth_model: AuthModel,
    *,
    secret: str = "s3cret",  # noqa: S107 - the fake's test secret
    kind: CredentialKind = CredentialKind.SECRET,
    folder: str = "INBOX",
) -> Mailbox:
    row = Mailbox(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        address=ADDRESS,
        protocol=protocol.value,
        auth_model=auth_model.value,
        client_id="app-1",
        directory_id="dir-1" if protocol is MailboxProtocol.GRAPH else None,
        credential_kind=kind.value,
        security="tls",
        folder=folder,
    )
    row.secret_key_id, row.secret_sealed = ring.seal(TENANT, SECRET_PURPOSE, secret.encode())
    return row


def _signed_in(fake: FakeProviders, ring: KeyRing, row: Mailbox, account: str = ADDRESS) -> None:
    token = f"rt-{uuid.uuid4().hex}"
    fake.refresh_tokens[token] = account
    row.token_key_id, row.token_sealed = ring.seal(TENANT, TOKEN_PURPOSE, token.encode())


def _certificate(key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey, days: int = 30) -> str:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SupportX mail")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=days))
        .sign(key, hashes.SHA256())
    )
    pem_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return pem_key.decode() + cert.public_bytes(serialization.Encoding.PEM).decode()


# --- domain rules --------------------------------------------------------------------------------


def test_least_privilege_scopes() -> None:
    """Read, mark and move only: never sending, never full mailbox access (REQ-INT-050)."""
    assert scopes_for(MailboxProtocol.GMAIL, AuthModel.DELEGATED) == (
        "https://www.googleapis.com/auth/gmail.modify",
    )
    assert scopes_for(MailboxProtocol.GRAPH, AuthModel.DELEGATED) == (
        "offline_access",
        "https://graph.microsoft.com/Mail.ReadWrite",
    )
    assert scopes_for(MailboxProtocol.GRAPH, AuthModel.APP) == (
        "https://graph.microsoft.com/.default",
    )
    every = {s for p in MailboxProtocol for m in AuthModel for s in scopes_for(p, m)}
    assert not any("Send" in s or "mail.google.com" in s for s in every)


def test_oauth_settings_are_checked() -> None:
    def problems(protocol: MailboxProtocol, **values: object) -> list[tuple[str, str]]:
        base: dict[str, object] = {
            "auth_model": AuthModel.DELEGATED,
            "credential_kind": CredentialKind.SECRET,
            "client_id": "c",
            "directory_id": "d",
            "has_credential": True,
        }
        return oauth_problems(protocol, **(base | values))  # type: ignore[arg-type]  # test table of keyword values

    assert problems(MailboxProtocol.IMAP, client_id=None) == []
    assert problems(MailboxProtocol.GRAPH) == []
    assert problems(MailboxProtocol.GRAPH, directory_id=None) == [("directory_id", "required")]
    assert problems(MailboxProtocol.GRAPH, has_credential=False) == [("client_secret", "required")]
    # Gmail without a sign-in would need domain-wide delegation: not offered.
    assert problems(MailboxProtocol.GMAIL, auth_model=AuthModel.APP) == [
        ("auth_model", "mailbox_auth_model_unsupported")
    ]
    assert problems(MailboxProtocol.GMAIL, credential_kind=CredentialKind.CERTIFICATE) == [
        ("credential_kind", "mailbox_auth_model_unsupported")
    ]


def test_an_expiring_credential_is_announced_once_per_expiry() -> None:
    now = datetime(2026, 10, 29, tzinfo=UTC)
    expires = now + timedelta(days=10)
    assert not credential_warning_due(now + timedelta(days=30), None, now)
    assert credential_warning_due(expires, None, now)
    assert not credential_warning_due(expires, now, now + timedelta(days=1))
    # A new secret with a later expiry is announced again when its own time comes.
    later = now + timedelta(days=200)
    assert credential_warning_due(later, now, later - timedelta(days=5))


# --- reading -------------------------------------------------------------------------------------


async def test_graph_app_permission_reads_marks_and_moves(
    fake: FakeProviders, ring: KeyRing, settings: Settings
) -> None:
    fake.deliver(ADDRESS, RAW)
    fake.deliver(ADDRESS, RAW.replace(b"Printer", b"Scanner"))
    row = _mailbox(ring, MailboxProtocol.GRAPH, AuthModel.APP)
    opened = await open_reader(row, ring, settings)
    try:
        found = await opened.reader.new_messages()
        assert [m.raw for m in found] == [RAW, RAW.replace(b"Printer", b"Scanner")]  # oldest first
        await opened.reader.done(found[0].uid, AfterFetch.MARK_READ)
        await opened.reader.done(found[1].uid, AfterFetch.MOVE, "Done")
    finally:
        await opened.reader.close()
    first, second = fake.mailboxes[ADDRESS]
    assert (first.unread, first.folder) == (False, "inbox")
    assert (second.unread, second.folder) == (False, "folder-done")
    # Application permission names the mailbox; nothing was sent through Graph.
    assert all(
        "/users/support@acme.test/" in str(r.url) for r in fake.requests if GRAPH in str(r.url)
    )
    assert not any("sendMail" in str(r.url) for r in fake.requests)


async def test_graph_app_permission_outside_its_scope_is_refused(
    fake: FakeProviders, ring: KeyRing, settings: Settings
) -> None:
    """RBAC for Applications limits the app to the support mailboxes (the admin guide, step 3)."""
    fake.deliver(ADDRESS, RAW)
    fake.allowed = {"other@acme.test"}
    opened = await open_reader(_mailbox(ring, MailboxProtocol.GRAPH, AuthModel.APP), ring, settings)
    with pytest.raises(MailboxUnavailableError) as refused:
        await opened.reader.new_messages()
    await opened.reader.close()
    assert refused.value.reason == OAUTH_NOT_ALLOWED


async def test_graph_with_a_certificate(
    fake: FakeProviders, ring: KeyRing, settings: Settings
) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    fake.public_key = key.public_key()
    fake.deliver(ADDRESS, RAW)
    pem = _certificate(key)
    row = _mailbox(
        ring, MailboxProtocol.GRAPH, AuthModel.APP, secret=pem, kind=CredentialKind.CERTIFICATE
    )
    opened = await open_reader(row, ring, settings)
    assert [m.raw for m in await opened.reader.new_messages()] == [RAW]
    await opened.reader.close()
    form = parse_qs(fake.requests[0].content.decode())
    assert "client_secret" not in form  # the key signs; it never leaves SupportX
    assert form["client_assertion_type"] == [
        "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
    ]
    assert load_certificate(pem).expires_at > datetime.now(UTC) + timedelta(days=29)


def test_an_unusable_certificate_is_refused() -> None:
    with pytest.raises(MailboxUnavailableError) as refused:
        load_certificate("not a certificate")
    assert refused.value.reason == OAUTH_CERTIFICATE_INVALID
    with pytest.raises(MailboxUnavailableError):  # Microsoft wants RS256: no EC keys
        load_certificate(_certificate(ec.generate_private_key(ec.SECP256R1())))


async def test_gmail_reads_oldest_first_marks_and_trashes(
    fake: FakeProviders, ring: KeyRing, settings: Settings
) -> None:
    fake.deliver(ADDRESS, RAW)
    fake.deliver(ADDRESS, RAW.replace(b"Printer", b"Scanner"))
    row = _mailbox(ring, MailboxProtocol.GMAIL, AuthModel.DELEGATED)
    _signed_in(fake, ring, row)
    opened = await open_reader(row, ring, settings)
    found = await opened.reader.new_messages()
    assert [m.raw for m in found] == [RAW, RAW.replace(b"Printer", b"Scanner")]
    await opened.reader.done(found[0].uid, AfterFetch.MARK_READ)
    await opened.reader.done(found[1].uid, AfterFetch.DELETE)
    await opened.reader.close()
    first, second = fake.mailboxes[ADDRESS]
    assert (first.unread, first.deleted) == (False, False)
    assert second.deleted  # to Trash: gmail.modify cannot erase mail
    assert all(GMAIL in str(r.url) or "token" in str(r.url) for r in fake.requests)


async def test_a_rotated_refresh_token_is_returned_to_keep(
    fake: FakeProviders, ring: KeyRing, settings: Settings
) -> None:
    fake.rotate = True
    row = _mailbox(ring, MailboxProtocol.GRAPH, AuthModel.DELEGATED)
    _signed_in(fake, ring, row)
    opened = await open_reader(row, ring, settings)
    await opened.reader.close()
    assert opened.new_refresh_token in fake.refresh_tokens


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ("invalid_grant", OAUTH_CONSENT_REVOKED),
        ("invalid_client", OAUTH_CLIENT_REJECTED),
        ("invalid_scope", OAUTH_NOT_ALLOWED),
    ],
)
async def test_token_refusals_become_reasons_without_provider_text(
    fake: FakeProviders, ring: KeyRing, settings: Settings, error: str, reason: str
) -> None:
    fake.refuse_with = error
    row = _mailbox(ring, MailboxProtocol.GMAIL, AuthModel.DELEGATED)
    _signed_in(fake, ring, row)
    with pytest.raises(MailboxUnavailableError) as refused:
        await open_reader(row, ring, settings)
    assert refused.value.reason == reason
    assert str(refused.value) == reason  # never the provider's description


@pytest.mark.usefixtures("fake")
async def test_a_wrong_secret_and_no_sign_in_are_reasons(ring: KeyRing, settings: Settings) -> None:
    row = _mailbox(ring, MailboxProtocol.GRAPH, AuthModel.APP, secret="wrong")
    with pytest.raises(MailboxUnavailableError) as refused:
        await open_reader(row, ring, settings)
    assert refused.value.reason == OAUTH_CLIENT_REJECTED
    gmail = _mailbox(ring, MailboxProtocol.GMAIL, AuthModel.DELEGATED)
    with pytest.raises(MailboxUnavailableError) as missing:
        await open_reader(gmail, ring, settings)
    assert missing.value.reason == OAUTH_NOT_CONNECTED


# --- consent -------------------------------------------------------------------------------------


@pytest.mark.parametrize("protocol", [MailboxProtocol.GMAIL, MailboxProtocol.GRAPH])
async def test_consent_round_trip(
    fake: FakeProviders, ring: KeyRing, settings: Settings, protocol: MailboxProtocol
) -> None:
    row = _mailbox(ring, protocol, AuthModel.DELEGATED)
    url = start_consent(row, ring, settings, admin_id=ADMIN, origin=ORIGIN)
    query = parse_qs(urlsplit(url).query)
    assert query["redirect_uri"] == [f"{ORIGIN}/api/v1/integrations/oauth/callback"]
    assert query["login_hint"] == [ADDRESS]
    state, code = fake.sign_in(ADDRESS, url)
    stored = row.oauth_state_hash
    assert stored is not None
    assert state not in stored  # only its hash is stored
    await finish_consent(row, ring, settings, code=code, admin_id=ADMIN, origin=ORIGIN)
    assert row.connected_account == ADDRESS
    assert row.token_sealed is not None
    assert row.oauth_state_hash is None  # used once
    refresh = ring.unseal(TENANT, TOKEN_PURPOSE, str(row.token_key_id), row.token_sealed).decode()
    assert fake.refresh_tokens[refresh] == ADDRESS
    if protocol is MailboxProtocol.GMAIL:
        assert query["access_type"] == ["offline"]


async def test_consent_as_another_account_is_refused(
    fake: FakeProviders, ring: KeyRing, settings: Settings
) -> None:
    """A refresh token never reads someone else's mail."""
    row = _mailbox(ring, MailboxProtocol.GMAIL, AuthModel.DELEGATED)
    url = start_consent(row, ring, settings, admin_id=ADMIN, origin=ORIGIN)
    _, code = fake.sign_in("ceo@acme.test", url)
    with pytest.raises(ConsentRefusedError) as refused:
        await finish_consent(row, ring, settings, code=code, admin_id=ADMIN, origin=ORIGIN)
    assert refused.value.reason == OAUTH_WRONG_ACCOUNT
    assert row.token_sealed is None


async def test_consent_for_someone_else_or_another_address_or_late_is_refused(
    fake: FakeProviders, ring: KeyRing, settings: Settings
) -> None:
    row = _mailbox(ring, MailboxProtocol.GMAIL, AuthModel.DELEGATED)
    _, code = fake.sign_in(
        ADDRESS, start_consent(row, ring, settings, admin_id=ADMIN, origin=ORIGIN)
    )
    with pytest.raises(ConsentRefusedError) as other_admin:
        await finish_consent(row, ring, settings, code=code, admin_id=uuid.uuid4(), origin=ORIGIN)
    assert other_admin.value.reason == CONSENT_NOT_YOURS
    with pytest.raises(ConsentRefusedError) as replayed:  # cleared: a state works once
        await finish_consent(row, ring, settings, code=code, admin_id=ADMIN, origin=ORIGIN)
    assert replayed.value.reason == CONSENT_EXPIRED

    _, code = fake.sign_in(
        ADDRESS, start_consent(row, ring, settings, admin_id=ADMIN, origin=ORIGIN)
    )
    with pytest.raises(ConsentRefusedError) as elsewhere:
        await finish_consent(
            row, ring, settings, code=code, admin_id=ADMIN, origin="https://evil.test"
        )
    assert elsewhere.value.reason == CONSENT_NOT_YOURS

    _, code = fake.sign_in(
        ADDRESS, start_consent(row, ring, settings, admin_id=ADMIN, origin=ORIGIN)
    )
    row.oauth_pending_until = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(ConsentRefusedError) as late:
        await finish_consent(row, ring, settings, code=code, admin_id=ADMIN, origin=ORIGIN)
    assert late.value.reason == CONSENT_EXPIRED
    assert row.token_sealed is None


def test_app_permission_needs_no_consent(ring: KeyRing, settings: Settings) -> None:
    row = _mailbox(ring, MailboxProtocol.GRAPH, AuthModel.APP)
    with pytest.raises(ConsentRefusedError):
        start_consent(row, ring, settings, admin_id=ADMIN, origin=ORIGIN)


def test_secrets_are_bound_to_their_purpose(ring: KeyRing) -> None:
    """A sealed client secret never opens as a refresh token (or for another tenant)."""
    row = _mailbox(ring, MailboxProtocol.GMAIL, AuthModel.DELEGATED)
    assert row.secret_key_id is not None
    assert row.secret_sealed is not None
    with pytest.raises(ValueError, match="does not open"):
        ring.unseal(TENANT, TOKEN_PURPOSE, row.secret_key_id, row.secret_sealed)
    with pytest.raises(ValueError, match="does not open"):
        ring.unseal(uuid.uuid4(), SECRET_PURPOSE, row.secret_key_id, row.secret_sealed)
    assert base64.b64encode(b"s3cret") not in row.secret_sealed
