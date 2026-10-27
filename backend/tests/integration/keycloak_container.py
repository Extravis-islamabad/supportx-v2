"""A private Keycloak for integration tests: one container per test process.

Tests never sign in to the shared dev Keycloak: another lane's run logging in or out the same
seeded users raced them (`login_failed`, 2026-10-27). Each pytest process (each xdist worker or
CI shard) starts its own container from the dev stack's image and realm file, on a free local
port, and removes it at the end. Inside and outside ports are the same (`--http-port`), so the
issuer, redirects and admin API agree without hostname settings.

Needs only the Docker CLI; `start()` returns None when Docker is missing so callers can skip.
"""

import os
import secrets
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

IMAGE = "quay.io/keycloak/keycloak:26.8.1"  # the dev stack's image (deploy/compose)
KEYCLOAK_FILES = Path(__file__).resolve().parents[3] / "deploy/helm/supportx/files/keycloak"
CONSOLE_ORIGIN = "http://localhost:5173"
PORTAL_ORIGIN = "http://localhost:5174"
LABEL = "supportx.test=keycloak"  # `docker ps -f label=supportx.test=keycloak` finds leftovers
READY_SECONDS = 240


@dataclass(frozen=True)
class PrivateKeycloak:
    """A running private Keycloak with the dev realm (`supportx`) and its seeded users."""

    name: str
    port: int
    console_secret: str
    portal_secret: str
    admin_user: str
    admin_password: str

    @property
    def base_url(self) -> str:
        return f"http://localhost:{self.port}"

    @property
    def issuer(self) -> str:
        return f"{self.base_url}/realms/supportx"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _mounts() -> list[str]:
    found = [
        ("dev", "/opt/keycloak/data/import"),
        ("themes/supportx", "/opt/keycloak/themes/supportx"),
        # The realm's password policy may name this list; the import fails without it.
        ("password-blacklists", "/opt/keycloak/data/password-blacklists"),
    ]
    args: list[str] = []
    for local, inside in found:
        path = KEYCLOAK_FILES / local
        if path.exists():
            args += ["-v", f"{path}:{inside}:ro"]
    return args


def start() -> PrivateKeycloak | None:
    """Start a private Keycloak and wait until its realm answers; None without Docker."""
    if shutil.which("docker") is None:
        return None
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    keycloak = PrivateKeycloak(
        name=f"supportx-test-kc-{worker}-{os.getpid()}-{secrets.token_hex(3)}",
        port=_free_port(),
        console_secret=secrets.token_hex(16),
        portal_secret=secrets.token_hex(16),
        admin_user="admin",
        admin_password=secrets.token_hex(16),
    )
    env = {
        "KC_BOOTSTRAP_ADMIN_USERNAME": keycloak.admin_user,
        "KC_BOOTSTRAP_ADMIN_PASSWORD": keycloak.admin_password,
        "JAVA_OPTS_KC_HEAP": "-XX:MaxRAMPercentage=65",
        "SUPPORTX_KC_CONSOLE_SECRET": keycloak.console_secret,
        "SUPPORTX_KC_PORTAL_SECRET": keycloak.portal_secret,
        "SUPPORTX_KC_CONSOLE_ORIGIN": CONSOLE_ORIGIN,
        "SUPPORTX_KC_PORTAL_ORIGIN": PORTAL_ORIGIN,
        "SUPPORTX_BRANDING_URL": f"{CONSOLE_ORIGIN}/api/v1/public/branding",
    }
    command = [
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        keycloak.name,
        "--label",
        LABEL,
        "-m",
        "1g",
        "-p",
        f"127.0.0.1:{keycloak.port}:{keycloak.port}",
        *[part for key, value in env.items() for part in ("-e", f"{key}={value}")],
        *_mounts(),
        IMAGE,
        "start-dev",
        "--import-realm",
        f"--http-port={keycloak.port}",
    ]
    subprocess.run(command, check=True, capture_output=True)  # noqa: S603 - fixed argv, no shell
    try:
        _wait_ready(keycloak)
    except BaseException:
        stop(keycloak)
        raise
    return keycloak


def _wait_ready(keycloak: PrivateKeycloak) -> None:
    deadline = time.monotonic() + READY_SECONDS
    url = f"{keycloak.issuer}/.well-known/openid-configuration"
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    logs = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["docker", "logs", "--tail", "40", keycloak.name],  # noqa: S607 - docker from PATH
        capture_output=True,
        text=True,
        check=False,
    )
    msg = f"private Keycloak {keycloak.name} not ready after {READY_SECONDS}s:\n{logs.stdout}"
    raise TimeoutError(msg + logs.stderr)


def stop(keycloak: PrivateKeycloak) -> None:
    """Remove the container this process started (never any other)."""
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["docker", "rm", "-f", keycloak.name],  # noqa: S607 - docker from PATH
        capture_output=True,
        check=False,
    )
