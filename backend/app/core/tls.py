"""TLS to the installation's own backing services: Valkey, NATS, PostgreSQL (audit row 5).

One way to build the client context, so every connection inside the cluster checks the same
things: the server's certificate chains to the configured CA, its name matches the host dialled
(never only "some certificate from that CA"), and nothing older than TLS 1.2 is spoken. The CA
file is mounted by the chart (docs/deployment.md, Transport security); configuration decides,
never the deployment mode (CLAUDE.md rule 5f).
"""

import ssl
from pathlib import Path
from urllib.parse import urlsplit


def verified_context(ca_file: Path) -> ssl.SSLContext:
    """A client context trusting only `ca_file`, with the host name always checked."""
    # cafile alone, not the system store: an in-cluster CA is private, and a public CA has no
    # business vouching for a pod's name.
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca_file))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def nats_tls(url: str, ca_file: Path | None) -> tuple[ssl.SSLContext | None, str | None]:
    """nats-py's `tls` and `tls_hostname` for `url`: (None, None) without a CA file.

    The host name is pinned to the one in the URL (the service name, which every NATS server's
    certificate lists): servers the cluster announces are dialled by address, and checking
    those against the certificate would fail, or tempt a wildcard over addresses.
    """
    if ca_file is None:
        return None, None
    return verified_context(ca_file), urlsplit(url).hostname
