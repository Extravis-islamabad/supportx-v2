"""The sign-in key ring (D-162, ADR-048): settings, the session cipher, and the untangled secrets.

Rotating the ring (a new newest key) must leave every other user of the old session secret as
it was: list cursors, API-key hashes and custom-domain proofs keep today's derivations.
"""

import hashlib
import hmac
import json
import os
from collections.abc import Callable
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ServiceUnavailable
from app.modules.identity_access.infra.crypto import SessionCipher, session_ring
from app.modules.identity_access.service.api_keys import legacy_server_key, server_key
from app.modules.organization.api.domains import domain_secret
from app.modules.organization.domain.domains import proof
from app.modules.system import build_readiness_service
from app.modules.system.domain.readiness import CheckStatus, FailureReason
from app.shared.api.listing import CursorCodec
from app.shared.crypto import key_id_of
from conftest import make_settings

if TYPE_CHECKING:
    from fastapi import Request

LEGACY = "L" * 40
NEW = "N" * 40


def keys(*items: dict[str, str]) -> str:
    return json.dumps(list(items))


def v1_blob(secret: str, payload: dict[str, object], bound_to: str) -> bytes:
    """A record as sealed before D-162 (crypto.py's old derivation, byte for byte)."""
    aead = AESGCM(hashlib.sha256(b"supportx/bff-session/v1" + secret.encode()).digest())
    nonce = os.urandom(12)
    return nonce + aead.encrypt(nonce, json.dumps(payload).encode(), bound_to.encode())


# --- settings -------------------------------------------------------------------------------------


def test_the_session_secret_alone_is_a_one_key_ring_called_legacy() -> None:
    settings = make_settings(session_secret=LEGACY)
    assert settings.session_key_entries() == (("legacy", LEGACY),)
    assert settings.auth_configured is False  # no issuer: unchanged by the ring
    assert make_settings().session_key_entries() == ()


def test_with_both_the_ring_is_session_keys_and_legacy_may_be_listed_by_id() -> None:
    settings = make_settings(
        session_secret=LEGACY,
        session_keys=keys({"id": "2026-11", "secret": NEW}, {"id": "legacy"}),
    )
    assert [k for k, _ in settings.session_key_entries()] == ["2026-11", "legacy"]
    assert dict(settings.session_key_entries())["legacy"] == LEGACY
    without_legacy = make_settings(
        session_secret=LEGACY, session_keys=keys({"id": "2026-11", "secret": NEW})
    )
    assert [k for k, _ in without_legacy.session_key_entries()] == ["2026-11"]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("not json", "must be JSON"),
        ("[]", "non-empty list"),
        ('{"id": "a"}', "non-empty list"),
        (keys({"id": "Bad", "secret": NEW}), "key IDs"),
        (keys({"id": "a", "secret": NEW}, {"id": "a", "secret": NEW}), "unique"),
        (keys({"id": "a"}), "needs a secret"),
        ('[{"id": "a", "secret": "x", "note": 1}]', "nothing else"),
        (keys({"id": "legacy", "secret": NEW}), "must be SUPPORTX_SESSION_SECRET"),
    ],
)
def test_malformed_session_keys_are_refused_without_showing_a_secret(
    value: str, message: str
) -> None:
    with pytest.raises(ValidationError, match=message) as refused:
        make_settings(session_secret=LEGACY, session_keys=value)
    assert NEW not in str(refused.value)
    assert LEGACY not in str(refused.value)


def test_every_ring_key_but_legacy_needs_32_bytes_in_every_profile() -> None:
    with pytest.raises(ValidationError, match="'k2' needs at least 32 bytes") as refused:
        make_settings(session_keys=keys({"id": "k2", "secret": "s" * 31}))
    assert "s" * 31 not in str(refused.value)
    # Bytes, not characters: 16 two-byte characters are 32 bytes.
    assert make_settings(session_keys=keys({"id": "k2", "secret": "é" * 16})).session_key_entries()
    # "legacy" stays as it was before D-162, whatever its length outside production.
    short_legacy = make_settings(
        session_secret="old", session_keys=keys({"id": "k2", "secret": NEW}, {"id": "legacy"})
    )
    assert dict(short_legacy.session_key_entries())["legacy"] == "old"
    assert session_ring(short_legacy) is not None


def test_the_ring_builder_refuses_a_short_key_too() -> None:
    def entries() -> tuple[tuple[str, str], ...]:
        return (("k2", "s" * 31), ("legacy", "old"))

    settings = cast("Settings", SimpleNamespace(session_key_entries=entries))
    with pytest.raises(ValueError, match="'k2' needs at least 32 bytes"):
        session_ring(settings)


def test_legacy_by_id_needs_the_session_secret() -> None:
    with pytest.raises(ValidationError, match="needs a secret"):
        make_settings(session_keys=keys({"id": "legacy"}))


def test_production_accepts_a_ring_with_the_legacy_secret(
    production_settings: Callable[..., Settings],
) -> None:
    settings = production_settings(session_keys=keys({"id": "k2", "secret": NEW}))
    assert settings.auth_configured is True
    with pytest.raises(ValidationError, match="'k2' needs at least 32 bytes"):
        production_settings(session_keys=keys({"id": "k2", "secret": "short"}))


def test_production_refuses_a_ring_that_would_end_cursors_and_domain_proofs(
    production_settings: Callable[..., Settings],
) -> None:
    ring = keys({"id": "k2", "secret": NEW})
    with pytest.raises(ValidationError, match="session_keys_need_legacy_secret") as refused:
        production_settings(session_secret=None, session_keys=ring)
    for name in ("CURSOR_SECRET", "DOMAIN_PROOF_SECRET"):
        assert f"SUPPORTX_{name}" in str(refused.value)
    accepted = production_settings(
        session_secret=None,
        session_keys=ring,
        cursor_secret="c" * 40,
        domain_proof_secret="d" * 40,
    )
    assert accepted.session_key_entries() == (("k2", NEW),)
    with pytest.raises(ValidationError, match="SUPPORTX_SESSION_SECRET"):
        production_settings(session_secret=None)  # neither: a session key is required


def test_production_requires_its_own_api_key_secret(
    production_settings: Callable[..., Settings],
) -> None:
    """Audit row 26: the session secret never guards API keys in production."""
    with pytest.raises(ValidationError, match="SUPPORTX_API_KEY_SECRET"):
        production_settings(api_key_secret=None)
    with pytest.raises(ValidationError, match="SUPPORTX_API_KEY_SECRET must be at least 32"):
        production_settings(api_key_secret="short")
    own = production_settings(api_key_secret="K" * 40)
    assert server_key(own) == b"K" * 40
    # Hashes made under the session-secret key still verify (and move) while it stays set.
    derived = hmac.new(b"s" * 32, b"supportx-api-keys-v1", hashlib.sha256).digest()
    assert legacy_server_key(own) == derived
    assert (
        legacy_server_key(
            production_settings(
                api_key_secret="K" * 40,
                session_secret=None,
                session_keys=keys({"id": "k2", "secret": NEW}),
                cursor_secret="c" * 40,
                domain_proof_secret="d" * 40,
            )
        )
        is None
    )


def test_dev_and_test_still_derive_the_api_key_key_without_the_setting() -> None:
    settings = make_settings(session_secret=LEGACY)
    assert (
        server_key(settings)
        == hmac.new(LEGACY.encode(), b"supportx-api-keys-v1", hashlib.sha256).digest()
    )
    assert legacy_server_key(settings) is None  # the derived key is already the current one


# --- the session cipher ---------------------------------------------------------------------------


def test_a_v1_record_opens_with_legacy_and_every_write_is_v2_under_the_newest() -> None:
    old = v1_blob(LEGACY, {"user": "u1"}, "sx:session:abc")
    ring = session_ring(
        make_settings(
            session_secret=LEGACY,
            session_keys=keys({"id": "k2", "secret": NEW}, {"id": "legacy"}),
        )
    )
    assert ring is not None
    cipher = SessionCipher(ring)
    assert cipher.decrypt(old, bound_to="sx:session:abc") == {"user": "u1"}
    assert cipher.decrypt(old, bound_to="sx:session:other") is None
    rewritten = cipher.encrypt({"user": "u1"}, bound_to="sx:session:abc")
    assert key_id_of(rewritten) == "k2"
    assert cipher.is_current(rewritten)
    assert cipher.decrypt(rewritten, bound_to="sx:session:abc") == {"user": "u1"}


def test_a_v1_record_whose_first_byte_looks_like_the_header_still_opens() -> None:
    cipher = SessionCipher(LEGACY)
    for _ in range(2000):
        old = v1_blob(LEGACY, {"n": 1}, "k")
        if old[0] == 0x02:
            break
    else:  # pragma: no cover - 1 in 256 per try; 2000 tries all missing is ~1e-4 of 1e-3
        pytest.skip("no v1 blob starting with 0x02 drawn")
    assert cipher.decrypt(old, bound_to="k") == {"n": 1}


def test_v1_records_close_once_legacy_leaves_the_ring() -> None:
    old = v1_blob(LEGACY, {"user": "u1"}, "k")
    settings = make_settings(session_secret=LEGACY, session_keys=keys({"id": "k2", "secret": NEW}))
    cipher = SessionCipher.from_settings(settings)
    assert cipher is not None
    assert cipher.decrypt(old, bound_to="k") is None


def test_a_record_sealed_under_legacy_survives_adding_a_newer_key() -> None:
    before = SessionCipher.from_settings(make_settings(session_secret=LEGACY))
    assert before is not None
    blob = before.encrypt({"user": "u1"}, bound_to="k")
    assert key_id_of(blob) == "legacy"
    after = SessionCipher.from_settings(
        make_settings(
            session_secret=LEGACY,
            session_keys=keys({"id": "k2", "secret": NEW}, {"id": "legacy"}),
        )
    )
    assert after is not None
    assert after.decrypt(blob, bound_to="k") == {"user": "u1"}
    assert not after.is_current(blob)


# --- untangled: rotating the ring changes nothing else --------------------------------------------


def _domain_secret(settings: Settings) -> bytes:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))
    return domain_secret(cast("Request", request))


def test_rotating_the_ring_leaves_cursors_api_keys_and_domain_proofs_unchanged() -> None:
    before = make_settings(session_secret=LEGACY)
    rotated = make_settings(
        session_secret=LEGACY,
        session_keys=keys({"id": "k3", "secret": "3" * 40}, {"id": "legacy"}),
    )
    rotated_again = make_settings(
        session_secret=LEGACY, session_keys=keys({"id": "k4", "secret": "4" * 40})
    )
    # Today's derivations, byte for byte, so existing cursors, API keys and proofs keep working.
    cursor_key = hmac.new(LEGACY.encode(), b"supportx-cursor-v1", hashlib.sha256).digest()
    api_key = hmac.new(LEGACY.encode(), b"supportx-api-keys-v1", hashlib.sha256).digest()
    for settings in (before, rotated, rotated_again):
        assert CursorCodec.from_settings(settings)._key == cursor_key  # noqa: SLF001 - the key itself
        assert server_key(settings) == api_key
        assert _domain_secret(settings) == LEGACY.encode()
        assert proof(_domain_secret(settings), "token") == proof(LEGACY.encode(), "token")


def test_the_domain_proof_uses_its_own_secret_when_set() -> None:
    own = make_settings(session_secret=LEGACY, domain_proof_secret="D" * 40)
    assert _domain_secret(own) == b"D" * 40
    with pytest.raises(ServiceUnavailable):
        _domain_secret(make_settings(session_keys=keys({"id": "k2", "secret": NEW})))


# --- readiness ------------------------------------------------------------------------------------


async def test_ready_warns_but_stays_ready_above_three_listed_keys() -> None:
    ring = keys(*({"id": f"k{n}", "secret": NEW} for n in range(4)))
    report = await build_readiness_service(make_settings(session_keys=ring)).check()
    check = report.checks["session_keys"]
    assert (check.status, check.reason, check.critical) == (
        CheckStatus.FAILED,
        FailureReason.TOO_MANY_KEYS,
        False,
    )
    three = keys(*({"id": f"k{n}", "secret": NEW} for n in range(3)))
    fine = await build_readiness_service(make_settings(session_keys=three)).check()
    assert fine.checks["session_keys"].status is CheckStatus.OK
    assert "session_keys" not in (await build_readiness_service(make_settings()).check()).checks
