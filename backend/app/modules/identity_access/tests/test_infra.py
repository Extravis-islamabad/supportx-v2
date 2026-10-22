import time
from datetime import timedelta

import httpx
import pytest

from app.modules.identity_access.infra.crypto import SessionCipher
from app.modules.identity_access.infra.oidc import (
    ClientCredentials,
    IdentityProviderUnavailable,
    InvalidTokenError,
    OidcClient,
    PkcePair,
    TokenRejectedError,
    verify_rs256,
)
from app.modules.identity_access.infra.store import SessionStore
from app.modules.identity_access.tests.fake_idp import ISSUER, FakeIdp, FakeUser, MemoryKeyValue

CLIENT = ClientCredentials(
    "supportx-console", "secret", "http://localhost:5173/api/v1/auth/callback"
)


def test_cipher_round_trip_and_tamper_detection() -> None:
    cipher = SessionCipher("k" * 40)
    blob = cipher.encrypt({"refresh_token": "rt"}, bound_to="key-a")
    assert b"rt" not in blob
    assert cipher.decrypt(blob, bound_to="key-a") == {"refresh_token": "rt"}
    assert cipher.decrypt(blob, bound_to="key-b") is None  # moved to another key
    assert cipher.decrypt(blob[:-1] + bytes([blob[-1] ^ 1]), bound_to="key-a") is None
    assert SessionCipher("other-secret").decrypt(blob, bound_to="key-a") is None
    assert cipher.decrypt(b"short", bound_to="key-a") is None
    assert cipher.encrypt({}, bound_to="k") != cipher.encrypt({}, bound_to="k")  # fresh nonces


async def test_store_hashes_keys_and_login_state_is_single_use() -> None:
    kv = MemoryKeyValue()
    store = SessionStore(kv, SessionCipher("k" * 40))
    await store.put_session("cookie-value", {"x": 1}, timedelta(minutes=5))
    assert all("cookie-value" not in key for key in kv.data)
    assert await store.get_session("cookie-value") == {"x": 1}
    assert await store.get_session("other") is None
    await store.delete_session("cookie-value")
    assert await store.get_session("cookie-value") is None

    await store.put_login("state-1", {"nonce": "n"}, timedelta(minutes=10))
    assert await store.take_login("state-1") == {"nonce": "n"}
    assert await store.take_login("state-1") is None  # replayed callback

    assert await store.lock("s", timedelta(seconds=5)) is True
    assert await store.lock("s", timedelta(seconds=5)) is False
    await store.unlock("s")
    assert await store.lock("s", timedelta(seconds=5)) is True


def test_pkce_pair_is_s256() -> None:
    pair = PkcePair.generate()
    assert len(pair.verifier) >= 43
    assert pair.challenge != pair.verifier
    assert "=" not in pair.challenge
    assert PkcePair.generate().verifier != pair.verifier


def test_rs256_verification() -> None:
    idp = FakeIdp()
    jwks = idp.handler(httpx.Request("GET", f"{ISSUER}/protocol/openid-connect/certs")).json()
    token = idp.sign({"sub": "x"})
    assert verify_rs256(token, jwks) == {"sub": "x"}
    header, _payload, signature = token.split(".")
    forged_payload = idp.sign({"sub": "admin"}).split(".")[1]
    with pytest.raises(InvalidTokenError, match="signature"):
        verify_rs256(f"{header}.{forged_payload}.{signature}", jwks)
    with pytest.raises(InvalidTokenError, match="algorithm"):
        verify_rs256(idp.sign({"sub": "x"}, alg="none"), jwks)
    with pytest.raises(InvalidTokenError, match="signature"):
        verify_rs256(FakeIdp().sign({"sub": "x"}), jwks)  # other key, same kid
    with pytest.raises(InvalidTokenError, match="malformed"):
        verify_rs256("not.a.jwt!", jwks)


async def test_oidc_client_flow_against_fake_idp() -> None:
    idp = FakeIdp()
    oidc = OidcClient(ISSUER, idp.client())
    pkce = PkcePair.generate()
    url = await oidc.authorization_url(CLIENT, state="st", nonce="nn", pkce=pkce)
    assert "code_challenge_method=S256" in url
    assert "scope=openid+profile+email+organization%3A%2A" in url
    code, state = idp.issue_code(url, FakeUser("sub-1", "a@b.test", "A"))
    assert state == "st"
    tokens = await oidc.exchange_code(CLIENT, code=code, verifier=pkce.verifier)
    claims = await oidc.verify_id_token(tokens.id_token)
    assert claims["nonce"] == "nn"
    with pytest.raises(TokenRejectedError):
        await oidc.exchange_code(CLIENT, code=code, verifier=pkce.verifier)  # codes are single-use
    refreshed = await oidc.refresh(CLIENT, tokens.refresh_token)
    assert refreshed.refresh_token != tokens.refresh_token
    assert await oidc.end_session(CLIENT, refreshed.refresh_token) is True
    assert idp.ended_sessions == [refreshed.refresh_token]


async def test_key_rotation_refetches_jwks_once() -> None:
    idp = FakeIdp()
    oidc = OidcClient(ISSUER, idp.client())
    await oidc.jwks()  # cache the old key set
    idp.key, idp.kid = FakeIdp().key, "kid-2"
    assert (await oidc.verify_id_token(idp.sign({"sub": "x"})))["sub"] == "x"


async def test_unreachable_keycloak_is_a_clean_503() -> None:
    idp = FakeIdp(available=False)
    oidc = OidcClient(ISSUER, idp.client())
    with pytest.raises(IdentityProviderUnavailable) as raised:
        await oidc.authorization_url(CLIENT, state="s", nonce="n", pkce=PkcePair.generate())
    assert raised.value.instance_code == "identity_provider_unavailable"
    assert raised.value.status == 503


async def test_metadata_is_cached() -> None:
    calls: list[str] = []
    idp = FakeIdp()

    def counting(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return idp.handler(request)

    oidc = OidcClient(ISSUER, httpx.AsyncClient(transport=httpx.MockTransport(counting)))
    started = time.monotonic()
    await oidc.metadata()
    await oidc.metadata()
    assert len(calls) == 1
    assert time.monotonic() - started < 1
