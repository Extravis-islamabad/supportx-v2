"""IMAP connects to the pinned address, never the name, and TLS checks the name (audit #3).

A real TLS handshake against a local IMAP responder: a certificate for the typed name passes, a
mismatched one fails, and a plain connection whose name cannot resolve still reaches the pinned
address (so the name was never looked up).
"""

import datetime as dt
import imaplib
import ipaddress
import socket
import ssl
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.modules.integrations.infra.imap import _PinnedIMAP4, _PinnedIMAP4SSL

NAME = "mail.example.test"


def _certificate(directory: Path) -> tuple[Path, Path]:
    """A self-signed certificate for NAME (its own CA), and its key."""
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, NAME)])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(NAME)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def _serve_one(conn: socket.socket) -> None:
    """A minimal IMAP responder: the greeting, CAPABILITY, then LOGOUT."""
    with conn:
        conn.sendall(b"* OK IMAP ready\r\n")
        reader = conn.makefile("rb")
        for line in reader:
            tag, _, command = line.decode().partition(" ")
            if command.upper().startswith("CAPABILITY"):
                conn.sendall(f"* CAPABILITY IMAP4rev1\r\n{tag} OK done\r\n".encode())
            elif command.upper().startswith("LOGOUT"):
                conn.sendall(f"* BYE\r\n{tag} OK bye\r\n".encode())
                return


@contextmanager
def _server(tls: ssl.SSLContext | None) -> Iterator[int]:
    """A local IMAP responder on 127.0.0.1 (TLS when `tls`); yields its port."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def run() -> None:
        try:
            raw, _ = listener.accept()
        except OSError:
            return
        if tls is None:
            _serve_one(raw)
            return
        try:
            _serve_one(tls.wrap_socket(raw, server_side=True))
        except (ssl.SSLError, OSError):
            raw.close()  # the client refused our certificate

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        listener.close()
        thread.join(timeout=5)


@pytest.fixture
def tls_pair() -> Iterator[tuple[ssl.SSLContext, ssl.SSLContext]]:
    """(server context, client context trusting only our certificate)."""
    with tempfile.TemporaryDirectory() as folder:
        cert, key = _certificate(Path(folder))
        server = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        server.load_cert_chain(cert, key)
        client = ssl.create_default_context(cafile=str(cert))
        yield server, client


def test_tls_to_the_pinned_address_passes_for_the_certificate_s_name(
    tls_pair: tuple[ssl.SSLContext, ssl.SSLContext],
) -> None:
    server, client = tls_pair
    with _server(server) as port:
        imap = _PinnedIMAP4SSL(NAME, port, "127.0.0.1", client, 5)
        assert imap.host == NAME  # the name, not the address: the certificate was checked on it
        imap.logout()


def test_tls_to_the_pinned_address_fails_for_another_name(
    tls_pair: tuple[ssl.SSLContext, ssl.SSLContext],
) -> None:
    server, client = tls_pair
    with _server(server) as port, pytest.raises(ssl.SSLCertVerificationError):
        _PinnedIMAP4SSL("evil.example.test", port, "127.0.0.1", client, 5)


def test_a_plain_connection_reaches_the_pinned_address_without_resolving_the_name() -> None:
    """`.invalid` never resolves (RFC 6761): reaching the server proves the name was not used."""
    with _server(None) as port:
        imap = _PinnedIMAP4("mail.nowhere.invalid", port, "127.0.0.1", 5)
        assert isinstance(imap, imaplib.IMAP4)
        assert ipaddress.ip_address(imap.sock.getpeername()[0]) == ipaddress.ip_address("127.0.0.1")
        imap.logout()
