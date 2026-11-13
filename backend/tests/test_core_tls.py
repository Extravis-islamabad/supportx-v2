"""TLS to the installation's own services (audit row 5): one verified client context.

No network beyond loopback: a throwaway CA, and a TLS server on 127.0.0.1 for the handshakes.
"""

import asyncio
import ssl
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.tls import nats_tls, verified_context
from tests.tls_certs import make_certs


def test_the_context_verifies_the_certificate_and_the_host_name(tmp_path: Path) -> None:
    context = verified_context(make_certs(tmp_path, ["db"]).ca)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    # Only the given CA: no system store, so no public CA can vouch for a pod's name.
    assert context.cert_store_stats()["x509_ca"] == 1


async def test_only_the_right_ca_and_host_name_complete_a_handshake(tmp_path: Path) -> None:
    certs_dir = tmp_path / "server"
    certs = make_certs(certs_dir, ["localhost"])
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_context.load_cert_chain(certs.cert, certs.key)

    async def serve(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()

    server = await asyncio.start_server(serve, "127.0.0.1", 0, ssl=server_context)
    port = server.sockets[0].getsockname()[1]
    other_ca = make_certs(tmp_path / "other", ["localhost"]).ca
    try:
        _reader, writer = await asyncio.open_connection(
            "127.0.0.1", port, ssl=verified_context(certs.ca), server_hostname="localhost"
        )
        writer.close()
        with pytest.raises(ssl.SSLCertVerificationError, match="Hostname mismatch"):
            await asyncio.open_connection(
                "127.0.0.1", port, ssl=verified_context(certs.ca), server_hostname="db"
            )
        with pytest.raises(ssl.SSLCertVerificationError):
            await asyncio.open_connection(
                "127.0.0.1", port, ssl=verified_context(other_ca), server_hostname="localhost"
            )
    finally:
        server.close()
        await server.wait_closed()


def test_nats_pins_the_host_name_to_the_url(tmp_path: Path) -> None:
    ca = make_certs(tmp_path, ["supportx-nats"]).ca
    context, host = nats_tls("tls://supportx:pw@supportx-nats:4222", ca)
    assert host == "supportx-nats"
    assert context is not None
    assert context.check_hostname is True
    assert nats_tls("nats://supportx-nats:4222", None) == (None, None)


def test_a_nats_ca_with_a_plaintext_url_is_refused_at_start(tmp_path: Path) -> None:
    ca = make_certs(tmp_path, ["supportx-nats"]).ca
    with pytest.raises(ValueError, match="tls://"):
        Settings.load(
            env_file=None,
            profile="test",
            nats_url=SecretStr("nats://supportx-nats:4222"),
            nats_tls_ca_file=ca,
        )
    found = Settings.load(
        env_file=None,
        profile="test",
        nats_url=SecretStr("tls://supportx-nats:4222"),
        nats_tls_ca_file=ca,
    )
    assert found.nats_tls_ca_file == ca
