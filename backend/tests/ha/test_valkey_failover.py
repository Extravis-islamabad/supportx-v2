"""HA Valkey (ADR-038): Sentinel fails over, and a restarted master rejoins as a replica.

Renders the HA chart's own Valkey scripts (deploy/helm/supportx, values-ha.yaml) and runs three
containers on the official image, each a server and a sentinel like one pod, on a private
Docker network with the pods' hostnames. It removes everything afterwards.

It proves:
- the first start makes pod 0 master;
- stopping it promotes a replica, and data written before survives;
- the old master, started again, follows the new one (no split brain).

The app reconnecting through Sentinel is proven on k3d (the HA smoke), where the sentinels'
hostnames resolve for the app.

Runs with SUPPORTX_HA_TESTS=1 (CI job "valkey failover"); needs Docker and Helm.
"""

import os
import secrets
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

if (
    os.environ.get("SUPPORTX_HA_TESTS") != "1"
    or shutil.which("docker") is None
    or shutil.which("helm") is None
):
    pytest.skip("set SUPPORTX_HA_TESTS=1 (needs Docker and Helm)", allow_module_level=True)

pytestmark = pytest.mark.ha

ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / "deploy" / "helm" / "supportx"
HEADLESS = "supportx-valkey-headless.supportx.svc"


def _run(*args: str, check: bool = True) -> str:
    done = subprocess.run(list(args), check=check, capture_output=True, text=True)  # noqa: S603 - the test's own commands
    return done.stdout.strip()


def _scripts(into: Path) -> str:
    """The chart's HA Valkey scripts, written to `into`; returns the image the chart pins."""
    rendered = _run(
        "helm", "template", "supportx", str(CHART), "--namespace", "supportx",
        "-f", str(CHART / "values-ha.yaml"), "--show-only", "templates/valkey-ha.yaml",
        "--set", "publicUrl=https://x.example.com", "--set", "routing.hostnames={x.example.com}",
        "--set", "routing.gateway.tlsSecret=t",
    )  # fmt: skip
    # The scripts ConfigMap's `data:` holds `  <name>.sh: |` blocks indented four spaces.
    scripts: dict[str, list[str]] = {}
    current: list[str] | None = None
    configmap = next(doc for doc in rendered.split("\n---") if "kind: ConfigMap" in doc)
    for line in configmap.splitlines():
        if line.startswith("  ") and line.rstrip().endswith(".sh: |"):
            current = scripts.setdefault(line.strip().removesuffix(": |"), [])
        elif current is not None and (line.startswith("    ") or not line.strip()):
            current.append(line[4:])
        else:
            current = None
    assert set(scripts) == {"common.sh", "valkey.sh", "sentinel.sh"}, sorted(scripts)
    for name, lines in scripts.items():
        (into / name).write_text("\n".join(lines) + "\n")
    return next(
        line.split("image:", 1)[1].strip() for line in rendered.splitlines() if "image:" in line
    )


class Valkeys:
    """Three pods' worth of Valkey and Sentinel, by index."""

    def __init__(self, scripts: Path, image: str) -> None:
        self.scripts, self.image = scripts, image
        self.network = f"sx-vk-{uuid.uuid4().hex[:8]}"
        self.password = secrets.token_urlsafe(18)

    def name(self, index: int) -> str:
        return f"{self.network}-{index}"

    def start(self, index: int) -> None:
        _run(
            "docker", "run", "-d", "--name", self.name(index),
            "--hostname", f"supportx-valkey-{index}", "--network", self.network,
            "--network-alias", f"supportx-valkey-{index}.{HEADLESS}",
            "-e", f"VALKEY_PASSWORD={self.password}", "-v", f"{self.scripts}:/scripts:ro",
            "--tmpfs", "/run/valkey", "--tmpfs", "/run/sentinel", self.image,
            "sh", "-c", "sh /scripts/valkey.sh & sleep 2; sh /scripts/sentinel.sh",
        )  # fmt: skip

    def stop(self, index: int) -> None:
        _run("docker", "rm", "-f", self.name(index), check=False)

    def cli(self, index: int, *args: str, port: int = 6379) -> str:
        return _run(
            "docker", "exec", "-e", f"REDISCLI_AUTH={self.password}", self.name(index),
            "valkey-cli", "-p", str(port), "--no-auth-warning", *args,
        )  # fmt: skip

    def role(self, index: int) -> str:
        lines = [line.strip() for line in self.cli(index, "info", "replication").splitlines()]
        return next(line.split(":", 1)[1] for line in lines if line.startswith("role:"))  # \r\n

    def master(self, asked: int) -> str:
        found = self.cli(asked, "SENTINEL", "get-master-addr-by-name", "supportx", port=26379)
        return found.splitlines()[0] if found else ""


def _until(check: object, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if check():  # type: ignore[operator]  # a no-argument predicate
                return
        except subprocess.CalledProcessError:
            pass  # not up yet
        time.sleep(0.5)
    pytest.fail(f"not reached within {seconds} s")


@pytest.fixture
def valkeys(tmp_path: Path) -> Iterator[Valkeys]:
    tmp_path.chmod(0o755)  # the containers' own user reads the scripts
    found = Valkeys(tmp_path, _scripts(tmp_path))
    _run("docker", "network", "create", found.network)
    try:
        for index in range(3):
            found.start(index)
        yield found
    finally:
        for index in range(3):
            found.stop(index)
        _run("docker", "network", "rm", found.network, check=False)


def test_a_failover_keeps_the_data_and_the_old_master_rejoins_as_a_replica(
    valkeys: Valkeys,
) -> None:
    _until(lambda: [valkeys.role(i) for i in range(3)] == ["master", "slave", "slave"], 60)
    _until(lambda: valkeys.master(1).startswith("supportx-valkey-0."), 30)
    assert valkeys.cli(0, "set", "session:probe", "kept") == "OK"
    # Both replicas have it before the master is lost (WAIT: replicas that acknowledged).
    _until(lambda: valkeys.cli(0, "wait", "2", "1000") == "2", 60)

    valkeys.stop(0)
    _until(lambda: valkeys.master(1) not in ("", f"supportx-valkey-0.{HEADLESS}"), 60)
    promoted = int(valkeys.master(1).split(".")[0].rsplit("-", 1)[1])
    assert valkeys.role(promoted) == "master"
    assert valkeys.cli(promoted, "get", "session:probe") == "kept"

    valkeys.start(0)  # the former master comes back
    _until(lambda: valkeys.role(0) == "slave", 60)
    _until(lambda: valkeys.master(0).startswith(f"supportx-valkey-{promoted}."), 60)  # agrees
    _until(lambda: valkeys.cli(0, "get", "session:probe") == "kept", 30)
    masters = [i for i in range(3) if valkeys.role(i) == "master"]
    assert masters == [promoted]  # exactly one master: no split brain
