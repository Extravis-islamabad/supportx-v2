"""The IMAP reader against a real IMAP server (WP-024; REQ-INC-023 AC3, REQ-ADM-067).

A private GreenMail (test-only mail server, Apache-2.0) per test module, on free local ports,
removed at the end. Its TLS certificate is self-signed, so the TLS test also proves the reader
verifies certificates: it refuses with `imap_tls_failed` rather than trusting any server.
"""

import secrets
import shutil
import smtplib
import socket
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from email.message import EmailMessage

import pytest

from app.modules.integrations.domain.mailboxes import AfterFetch, ConnectionSecurity
from app.modules.integrations.infra.imap import ImapReader, ImapSettings, MailboxUnavailableError

IMAGE = "greenmail/standalone:2.1.3"
LABEL = "supportx.test=greenmail"
READY_SECONDS = 90
USER, PASSWORD, ADDRESS = "it@acme.test", "imap-secret", "it@acme.test"


@dataclass(frozen=True)
class MailServer:
    name: str
    smtp: int
    imap: int
    imaps: int


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _answers(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1) as conn:
            return conn.recv(4).startswith(b"* OK")
    except OSError:
        return False


@pytest.fixture(scope="module")
def server() -> Iterator[MailServer]:
    if shutil.which("docker") is None:
        pytest.skip("Docker is not available for a private mail server")
    found = MailServer(
        f"supportx-test-greenmail-{secrets.token_hex(3)}", _free_port(), _free_port(), _free_port()
    )
    options = " ".join(
        (
            "-Dgreenmail.setup.test.all",
            "-Dgreenmail.hostname=0.0.0.0",
            "-Dgreenmail.users.login=email",
            f"-Dgreenmail.users=it:{PASSWORD}@acme.test",
        )
    )
    subprocess.run(  # noqa: S603 - fixed arguments
        [  # noqa: S607 - docker from PATH, as the Keycloak test container
            "docker", "run", "-d", "--rm", "--name", found.name, "--label", LABEL,
            "-e", f"GREENMAIL_OPTS={options}",
            "-p", f"127.0.0.1:{found.smtp}:3025",
            "-p", f"127.0.0.1:{found.imap}:3143",
            "-p", f"127.0.0.1:{found.imaps}:3993",
            IMAGE,
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    try:
        deadline = time.monotonic() + READY_SECONDS
        while not _answers(found.imap):
            if time.monotonic() > deadline:
                pytest.fail("GreenMail did not start")
            time.sleep(0.5)
        yield found
    finally:
        subprocess.run(["docker", "rm", "-f", found.name], check=False, capture_output=True)  # noqa: S603, S607


def _send(server: MailServer, subject: str) -> None:
    message = EmailMessage()
    message["From"] = "Sara <sara@acme.test>"
    message["To"] = ADDRESS
    message["Subject"] = subject
    message.set_content("It jams.")
    with smtplib.SMTP("127.0.0.1", server.smtp, timeout=10) as smtp:
        smtp.send_message(message)


def _settings(server: MailServer, **overrides: object) -> ImapSettings:
    values: dict[str, object] = {
        "host": "127.0.0.1",
        "port": server.imap,
        "security": ConnectionSecurity.NONE,
        "username": USER,
        "password": PASSWORD,
    }
    return ImapSettings(**(values | overrides))  # type: ignore[arg-type]  # test overrides


async def test_new_mail_is_read_without_marking_it_until_done(server: MailServer) -> None:
    _send(server, "Printer jams")
    _send(server, "Screen flickers")
    reader = ImapReader(_settings(server))
    try:
        first = await reader.new_messages()
        assert sorted(b"Subject: Printer jams" in m.raw for m in first) == [False, True]
        again = await reader.new_messages()  # BODY.PEEK: still unseen until `done`
        assert [m.uid for m in again] == [m.uid for m in first]
        await reader.done(first[0].uid, AfterFetch.MARK_READ)
        left = await reader.new_messages()
        assert [m.uid for m in left] == [first[1].uid]
        await reader.done(first[1].uid, AfterFetch.MARK_READ)
        assert list(await reader.new_messages()) == []
    finally:
        await reader.close()


async def test_a_wrong_password_says_so(server: MailServer) -> None:
    reader = ImapReader(_settings(server, password="wrong"))
    with pytest.raises(MailboxUnavailableError) as refused:
        await reader.new_messages()
    assert refused.value.reason == "imap_login_failed"


async def test_a_server_whose_certificate_cannot_be_trusted_is_refused(
    server: MailServer,
) -> None:
    reader = ImapReader(_settings(server, port=server.imaps, security=ConnectionSecurity.TLS))
    with pytest.raises(MailboxUnavailableError) as refused:
        await reader.new_messages()
    assert refused.value.reason == "imap_tls_failed"
