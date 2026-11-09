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
import re
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
# Start-up on a busy CI runner: image already pulled, but three servers and sentinels to boot.
START_SECONDS = 90


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
    _read_timings("\n".join(scripts["sentinel.sh"]))
    for name, lines in scripts.items():
        (into / name).write_text("\n".join(lines) + "\n")
    return next(
        line.split("image:", 1)[1].strip() for line in rendered.splitlines() if "image:" in line
    )


# How long a failover may take, from the chart's own sentinel settings: noticing the master is
# gone (down-after-milliseconds), and, when Sentinel's first attempt is abandoned on a slow
# runner (a replica briefly looking unfit), its retry after twice the failover timeout. Waiting
# less than that made the test fail on slow runners although failover worked (2026-11-06).
TIMINGS: dict[str, float] = {}


def _read_timings(sentinel_script: str) -> None:
    for key, name in (("down", "down-after-milliseconds"), ("failover", "failover-timeout")):
        found = re.search(rf"sentinel {name} supportx (\d+)", sentinel_script)
        assert found is not None, f"{name} not in the chart's sentinel.sh"
        TIMINGS[key] = int(found.group(1)) / 1000


def failover_seconds() -> float:
    """Noticing, one abandoned attempt and its retry, plus a margin for the runner."""
    return TIMINGS["down"] + 2 * TIMINGS["failover"] + 20


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

    def start_plain(self, index: int) -> None:
        """A bare server as pod `index` (no sentinel, never replicated): keys at offset 0."""
        _run(
            "docker", "run", "-d", "--name", self.name(index),
            "--hostname", f"supportx-valkey-{index}", "--network", self.network,
            "--network-alias", f"supportx-valkey-{index}.{HEADLESS}", self.image,
            "valkey-server", "--requirepass", self.password, "--appendonly", "no",
        )  # fmt: skip

    def stop(self, index: int) -> None:
        _run("docker", "rm", "-f", self.name(index), check=False)

    def cut(self, index: int) -> None:
        """Take the pod off the network: it keeps running (and its data) but answers nobody."""
        _run("docker", "network", "disconnect", "-f", self.network, self.name(index))

    def rejoin(self, index: int) -> None:
        _run(
            "docker", "network", "connect", "--alias", f"supportx-valkey-{index}.{HEADLESS}",
            self.network, self.name(index),
        )  # fmt: skip

    def waiting(self, index: int) -> str:
        """Why the pod's server has not started yet (what the readiness probe prints), or ""."""
        done = subprocess.run(  # noqa: S603 - the test's own container
            ["docker", "exec", self.name(index), "cat", "/run/valkey/waiting"],  # noqa: S607
            check=False, capture_output=True, text=True,
        )  # fmt: skip
        return done.stdout.strip() if done.returncode == 0 else ""

    def serving(self, index: int) -> bool:
        try:
            return self.cli(index, "ping") == "PONG"
        except subprocess.CalledProcessError:
            return False

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


def replicated(valkeys: Valkeys) -> None:
    """Both replicas really hold the key. WAIT is not proof: in Valkey's dual-channel sync it can
    count a replica still loading (link down, offset 0; seen 2026-11-09)."""
    for index in (1, 2):
        _until(lambda i=index: valkeys.cli(i, "get", "session:probe") == "kept", 60)


@pytest.fixture
def valkeys(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Valkeys]:
    tmp_path.chmod(0o755)  # the containers' own user reads the scripts
    found = Valkeys(tmp_path, _scripts(tmp_path))
    _run("docker", "network", "create", found.network)
    failed_before = request.session.testsfailed
    try:
        for index in range(3):
            found.start(index)
        yield found
    finally:
        if request.session.testsfailed > failed_before:
            # What each pod decided ("starting as master", "replica of ..."), for the CI log.
            for index in range(3):
                logs = subprocess.run(  # noqa: S603 - the test's own container
                    ["docker", "logs", found.name(index)],  # noqa: S607
                    check=False,
                    capture_output=True,
                    text=True,
                )
                lines = (logs.stdout + logs.stderr).splitlines()
                # Sentinel's decisions (+sdown, +odown, +elected-leader, -failover-abort-...,
                # +switch-master) and each pod's start-up choice; the replicas' reconnect lines
                # (twice a second) would otherwise push them out of view.
                events = [
                    line
                    for line in lines
                    if re.search(r" [+-][a-z-]+ |starting as|replica of|master", line)
                    and "Connecting to PRIMARY" not in line
                ]
                shown = "\n".join([*events[-80:], "... last lines:", *lines[-20:]])
                print(f"--- pod {index} ---\n{shown}")  # noqa: T201

        for index in range(3):
            found.stop(index)
        _run("docker", "network", "rm", found.network, check=False)


def test_a_failover_keeps_the_data_and_the_old_master_rejoins_as_a_replica(
    valkeys: Valkeys,
) -> None:
    _until(
        lambda: [valkeys.role(i) for i in range(3)] == ["master", "slave", "slave"], START_SECONDS
    )
    _until(lambda: valkeys.master(1).startswith("supportx-valkey-0."), START_SECONDS)
    assert valkeys.cli(0, "set", "session:probe", "kept") == "OK"
    # Both replicas have it before the master is lost (WAIT: replicas that acknowledged).
    _until(lambda: valkeys.cli(0, "wait", "2", "1000") == "2", 60)
    replicated(valkeys)

    valkeys.stop(0)
    _until(
        lambda: valkeys.master(1) not in ("", f"supportx-valkey-0.{HEADLESS}"), failover_seconds()
    )
    promoted = int(valkeys.master(1).split(".")[0].rsplit("-", 1)[1])
    assert valkeys.role(promoted) == "master"
    assert valkeys.cli(promoted, "get", "session:probe") == "kept"

    valkeys.start(0)  # the former master comes back
    _until(lambda: valkeys.role(0) == "slave", failover_seconds())
    _until(
        lambda: valkeys.master(0).startswith(f"supportx-valkey-{promoted}."), failover_seconds()
    )  # agrees
    _until(lambda: valkeys.cli(0, "get", "session:probe") == "kept", 60)
    masters = [i for i in range(3) if valkeys.role(i) == "master"]
    assert masters == [promoted]  # exactly one master: no split brain


def test_a_master_back_before_the_sentinels_notice_never_starts_empty(valkeys: Valkeys) -> None:
    """The k3d HA smoke found it (2026-11-04): a force-deleted master pod was back in about 1 s,
    before down-after-milliseconds, so the sentinels still named it master and it started as an
    empty master; the replicas would then copy the empty set. It must hand over first. Seen
    again 2026-11-09: a peer it could not reach yet counted as "never synced", so it started
    empty and both replicas loaded 0 keys."""
    _until(
        lambda: [valkeys.role(i) for i in range(3)] == ["master", "slave", "slave"], START_SECONDS
    )
    _until(lambda: valkeys.master(1).startswith("supportx-valkey-0."), START_SECONDS)
    assert valkeys.cli(0, "set", "session:probe", "kept") == "OK"
    _until(lambda: valkeys.cli(0, "wait", "2", "1000") == "2", 60)
    replicated(valkeys)

    valkeys.stop(0)
    valkeys.start(0)  # at once: well inside down-after-milliseconds

    _until(
        lambda: valkeys.master(1) not in ("", f"supportx-valkey-0.{HEADLESS}"), failover_seconds()
    )
    promoted = int(valkeys.master(1).split(".")[0].rsplit("-", 1)[1])
    _until(lambda: valkeys.role(0) == "slave", failover_seconds())
    masters = [i for i in range(3) if valkeys.role(i) == "master"]
    assert masters == [promoted]
    for index in range(3):  # nobody lost the session
        _until(lambda i=index: valkeys.cli(i, "get", "session:probe") == "kept", 60)


def test_a_first_start_with_pod_0_last_is_still_quick(valkeys: Valkeys) -> None:
    """CI found it (2026-11-05, #211): when a peer's sentinel is up before pod 0, it names pod 0
    master, so pod 0 took the hand-over path and retried a failover for 60 s although no replica
    had ever synced (NOGOODSLAVE). Pod 0 last, on purpose: it must start as master at once."""
    for index in range(3):
        valkeys.stop(index)
    valkeys.start(2)
    valkeys.start(1)
    _until(
        lambda: valkeys.master(1) != "" or valkeys.master(2) != "", START_SECONDS
    )  # a sentinel names pod 0
    valkeys.start(0)
    _until(
        lambda: [valkeys.role(i) for i in range(3)] == ["master", "slave", "slave"], START_SECONDS
    )


def test_a_master_back_while_its_peers_are_unreachable_waits_and_keeps_the_data(
    valkeys: Valkeys,
) -> None:
    """Coordinator, 2026-11-09: a peer that does not answer may hold data, so a pod that would
    start as master waits, says why (the readiness probe prints it) and never starts empty."""
    _until(
        lambda: [valkeys.role(i) for i in range(3)] == ["master", "slave", "slave"], START_SECONDS
    )
    _until(lambda: valkeys.master(1).startswith("supportx-valkey-0."), START_SECONDS)
    assert valkeys.cli(0, "set", "session:probe", "kept") == "OK"
    _until(lambda: valkeys.cli(0, "wait", "2", "1000") == "2", 60)
    replicated(valkeys)

    valkeys.cut(1)
    valkeys.cut(2)
    valkeys.stop(0)
    valkeys.start(0)
    _until(lambda: "peers not answering" in valkeys.waiting(0), START_SECONDS)
    time.sleep(10)  # several more tries: still waiting, never serving an empty set
    assert not valkeys.serving(0)
    assert "cannot tell a fresh set" in valkeys.waiting(0)

    valkeys.rejoin(1)
    valkeys.rejoin(2)
    _until(lambda: valkeys.role(0) == "slave", failover_seconds() + START_SECONDS)
    assert valkeys.waiting(0) == ""
    masters = [i for i in range(3) if valkeys.role(i) == "master"]
    assert len(masters) == 1
    assert masters != [0]
    for index in range(3):  # nobody lost the session
        _until(lambda i=index: valkeys.cli(i, "get", "session:probe") == "kept", 60)


def test_a_fresh_install_waits_for_its_peers_then_starts(valkeys: Valkeys) -> None:
    """A fresh set whose peers come up late: pod 0 waits for them (it cannot know yet), then
    starts as master once every peer answers with nothing synced. It never deadlocks."""
    for index in range(3):
        valkeys.stop(index)
    valkeys.start(0)
    _until(lambda: "peers not answering" in valkeys.waiting(0), START_SECONDS)
    assert not valkeys.serving(0)
    valkeys.start(1)
    valkeys.start(2)
    _until(
        lambda: [valkeys.role(i) for i in range(3)] == ["master", "slave", "slave"], START_SECONDS
    )
    assert valkeys.waiting(0) == ""
    assert valkeys.cli(0, "set", "first", "ok") == "OK"


def test_a_peer_holding_keys_at_offset_0_is_never_read_as_empty(valkeys: Valkeys) -> None:
    """#284's own CI (2026-11-09): in Valkey's dual-channel sync a replica holds the data while
    it still reports offset 0, its link down. Pod 0 read that as a fresh set and the replicas
    loaded 0 keys. The same signal here: peers with keys and offset 0, and no sentinel."""
    for index in range(3):
        valkeys.stop(index)
    for index in (1, 2):
        valkeys.start_plain(index)
        _until(
            lambda i=index: valkeys.cli(i, "set", "session:probe", "kept") == "OK", START_SECONDS
        )
        info = valkeys.cli(index, "info", "replication")
        assert "master_repl_offset:0" in info  # the misleading offset, as in the CI run
    valkeys.start(0)
    _until(lambda: "holds data" in valkeys.waiting(0), START_SECONDS)
    time.sleep(6)  # several more tries: still waiting, never an empty master
    assert not valkeys.serving(0)
    assert "holds data" in valkeys.waiting(0)
    for index in (1, 2):  # nobody's keys were touched
        assert valkeys.cli(index, "get", "session:probe") == "kept"
