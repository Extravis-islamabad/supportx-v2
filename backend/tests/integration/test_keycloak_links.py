"""What Keycloak does with an earlier set-password link (QA WP-039 BUG-01, product owner).

"Send again" should stop the earlier link when Keycloak allows it, and otherwise the screen says
the earlier link still works. These tests pin Keycloak's side on the image the stack runs:

- it cannot withdraw one link: after a second e-mail, and even after ending the user's sessions
  (which sets their "not before"), the first link still opens the set-password form;
- a link names its account: once the account is made afresh (what "Send again" does for an
  account the invitation made), the earlier link no longer opens the form.

A private Keycloak and a private GreenMail (test-only mail server) on their own Docker network,
removed at the end; never the shared dev stack.
"""

import email
import imaplib
import re
import secrets
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass

import httpx
import pytest

from tests.integration.keycloak_container import IMAGE as KEYCLOAK_IMAGE

pytestmark = pytest.mark.integration

GREENMAIL_IMAGE = "greenmail/standalone:2.1.3"
LABEL = "supportx.test=keycloak-links"
READY_SECONDS = 240
REALM = "links"


@dataclass(frozen=True)
class Stack:
    network: str
    keycloak: str
    greenmail: str
    http_port: int
    imap_port: int
    admin_password: str

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.http_port}"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _docker(*args: str) -> None:
    subprocess.run(["docker", *args], check=True, capture_output=True)  # noqa: S603, S607


def _wait(url: str) -> None:
    deadline = time.monotonic() + READY_SECONDS
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    pytest.fail(f"not ready: {url}")


@pytest.fixture(scope="module")
def stack() -> Iterator[Stack]:
    if shutil.which("docker") is None:
        pytest.skip("Docker is not available for a private Keycloak")
    name = f"supportx-test-links-{secrets.token_hex(3)}"
    found = Stack(
        name, f"{name}-kc", f"{name}-gm", _free_port(), _free_port(), secrets.token_hex(16)
    )
    _docker("network", "create", "--label", LABEL, found.network)
    try:
        _docker(
            "run", "-d", "--rm", "--name", found.greenmail, "--label", LABEL,
            "--network", found.network,
            "-e", "GREENMAIL_OPTS=-Dgreenmail.setup.test.all -Dgreenmail.hostname=0.0.0.0"
            " -Dgreenmail.auth.disabled",
            "-p", f"127.0.0.1:{found.imap_port}:3143",
            GREENMAIL_IMAGE,
        )  # fmt: skip
        _docker(
            "run", "-d", "--rm", "--name", found.keycloak, "--label", LABEL, "-m", "1g",
            "--network", found.network,
            "-e", "KC_BOOTSTRAP_ADMIN_USERNAME=admin",
            "-e", f"KC_BOOTSTRAP_ADMIN_PASSWORD={found.admin_password}",
            "-p", f"127.0.0.1:{found.http_port}:{found.http_port}",
            KEYCLOAK_IMAGE, "start-dev", f"--http-port={found.http_port}",
        )  # fmt: skip
        _wait(f"{found.base}/realms/master/.well-known/openid-configuration")
        with _admin(found) as admin:
            admin.post(
                "/admin/realms",
                json={
                    "realm": REALM,
                    "enabled": True,
                    "smtpServer": {
                        "host": found.greenmail,
                        "port": "3025",
                        "from": "noreply@links.test",
                    },
                },
            ).raise_for_status()
        yield found
    finally:
        for container in (found.keycloak, found.greenmail):
            subprocess.run(["docker", "rm", "-f", container], check=False, capture_output=True)  # noqa: S603, S607
        subprocess.run(  # noqa: S603
            ["docker", "network", "rm", found.network],  # noqa: S607
            check=False,
            capture_output=True,
        )


def _admin(stack: Stack) -> httpx.Client:
    token = httpx.post(
        f"{stack.base}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "admin",
            "password": stack.admin_password,
        },
    ).json()["access_token"]
    return httpx.Client(base_url=stack.base, headers={"Authorization": f"Bearer {token}"})


def _account(admin: httpx.Client, name: str) -> str:
    made = admin.post(
        f"/admin/realms/{REALM}/users",
        json={"username": name, "email": f"{name}@links.test", "enabled": True},
    )
    made.raise_for_status()
    return made.headers["location"].rsplit("/", 1)[1]


def _send(admin: httpx.Client, user_id: str) -> None:
    admin.put(
        f"/admin/realms/{REALM}/users/{user_id}/execute-actions-email",
        params={"lifespan": 3600},
        json=["UPDATE_PASSWORD"],
    ).raise_for_status()


def _links(stack: Stack, name: str, count: int) -> list[str]:
    """The set-password links e-mailed to `name`, oldest first."""
    deadline = time.monotonic() + 30
    while True:
        mailbox = imaplib.IMAP4("127.0.0.1", stack.imap_port)
        try:
            mailbox.login(f"{name}@links.test", "any")
            mailbox.select("INBOX")
            _, found = mailbox.search(None, "ALL")
            links = []
            for number in (found[0] or b"").split():
                _, parts = mailbox.fetch(number.decode(), "(RFC822)")
                first = parts[0]
                assert isinstance(first, tuple)
                message = email.message_from_bytes(first[1])
                text = "".join(
                    (part.get_payload(decode=True) or b"").decode()  # type: ignore[union-attr]  # bytes for text parts
                    for part in message.walk()
                    if part.get_content_type() == "text/plain"
                )
                match = re.search(r"(http\S+action-token\S+)", text)
                assert match is not None, text
                links.append(match.group(1).rstrip(">"))
        finally:
            mailbox.logout()
        if len(links) >= count or time.monotonic() > deadline:
            return links
        time.sleep(0.5)


def _opens_the_form(link: str) -> bool:
    """Whether following the link (as a browser would) reaches the set-password form."""
    with httpx.Client(follow_redirects=True) as browser:
        page = browser.get(link)
        proceed = re.search(r'kc-info-message.*?<a href="([^"]+)"', page.text, re.DOTALL)
        if proceed is not None:
            for cookie in browser.cookies.jar:
                cookie.secure = False  # plain http on 127.0.0.1: let the client send them
            page = browser.get(proceed.group(1).replace("&amp;", "&"))
        return "password-new" in page.text


def test_keycloak_cannot_withdraw_an_earlier_link(stack: Stack) -> None:
    """Why the screen says earlier links still work for an account that existed before."""
    with _admin(stack) as admin:
        user_id = _account(admin, "kept")
        _send(admin, user_id)
        time.sleep(1.1)  # a later issue time
        admin.post(f"/admin/realms/{REALM}/users/{user_id}/logout").raise_for_status()
        time.sleep(1.1)
        _send(admin, user_id)
    first, second = _links(stack, "kept", 2)
    assert _opens_the_form(second)
    assert _opens_the_form(first)  # still works: nothing in Keycloak withdraws one link


def test_an_account_made_afresh_stops_the_earlier_link(stack: Stack) -> None:
    """What "Send again" does for an account the invitation made (BUG-01)."""
    with _admin(stack) as admin:
        first_account = _account(admin, "fresh")
        _send(admin, first_account)
        admin.delete(f"/admin/realms/{REALM}/users/{first_account}").raise_for_status()
        _send(admin, _account(admin, "fresh"))
    first, second = _links(stack, "fresh", 2)
    assert not _opens_the_form(first)
    assert _opens_the_form(second)
