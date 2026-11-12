"""HA Valkey (ADR-038): Sentinel fails over, and a restarted master rejoins as a replica.

Renders the HA chart's own Valkey scripts (deploy/helm/supportx, values-ha.yaml) and runs three
containers on the official image, each a server and a sentinel like one pod, on a private
Docker network with the pods' hostnames. It removes everything afterwards.

It proves:
- the first start makes pod 0 master;
- stopping it promotes a replica, and data written before survives;
- the old master, started again, follows the new one (no split brain);
- a pod is ready (ready.sh, the valkey container's probe) only once its own sentinel knows it in
  its role, so a planned stop right after a pod got ready still fails over; once ready, a
  sentinel outage never makes it not ready.

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
from itertools import pairwise
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


def _scripts(into: Path, *values: str) -> str:
    """The chart's HA Valkey scripts, written to `into`; returns the image the chart pins.
    `values` are extra `--set` values (the lone pod's replicas and quorum)."""
    rendered = _run(
        "helm", "template", "supportx", str(CHART), "--namespace", "supportx",
        "-f", str(CHART / "values-ha.yaml"), "--show-only", "templates/valkey-ha.yaml",
        "--set", "publicUrl=https://x.example.com", "--set", "routing.hostnames={x.example.com}",
        "--set", "routing.gateway.tlsSecret=t",
        *(arg for value in values for arg in ("--set", value)),
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
    assert set(scripts) == {"common.sh", "valkey.sh", "sentinel.sh", "ready.sh"}, sorted(scripts)
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
    """Three pods' worth of Valkey and Sentinel, by index (one for the lone pod)."""

    def __init__(self, scripts: Path, image: str, pods: int = 3) -> None:
        self.scripts, self.image, self.pods = scripts, image, pods
        self.network = f"sx-vk-{uuid.uuid4().hex[:8]}"
        self.password = secrets.token_urlsafe(18)

    def name(self, index: int) -> str:
        return f"{self.network}-{index}"

    def start(self, index: int, *, sentinel: bool = True) -> None:
        """The pod: its server and, unless held back (start_sentinel), its sentinel. The
        container lives while either runs, so a sentinel can stop on its own (stop_sentinel)."""
        both = "sh /scripts/valkey.sh & sleep 2; sh /scripts/sentinel.sh & wait"
        _run(
            "docker", "run", "-d", "--name", self.name(index),
            "--hostname", f"supportx-valkey-{index}", "--network", self.network,
            "--network-alias", f"supportx-valkey-{index}.{HEADLESS}",
            "-e", f"VALKEY_PASSWORD={self.password}", "-v", f"{self.scripts}:/scripts:ro",
            "--tmpfs", "/run/valkey", "--tmpfs", "/run/sentinel", self.image,
            "sh", "-c", both if sentinel else "sh /scripts/valkey.sh & wait",
        )  # fmt: skip

    def start_sentinel(self, index: int) -> None:
        _run("docker", "exec", "-d", self.name(index), "sh", "/scripts/sentinel.sh")

    def stop_sentinel(self, index: int) -> None:
        self.cli(index, "SHUTDOWN", port=26379, check=False)  # the connection drops: no answer

    def sentinel_up(self, index: int) -> bool:
        return self.cli(index, "ping", port=26379, check=False) == "PONG"

    def ready(self, index: int) -> tuple[bool, str]:
        """The valkey container's readiness probe, as Kubernetes runs it: passed, and its output."""
        done = subprocess.run(  # noqa: S603 - the test's own container
            ["docker", "exec", self.name(index), "sh", "/scripts/ready.sh"],  # noqa: S607
            check=False, capture_output=True, text=True,
        )  # fmt: skip
        return done.returncode == 0, (done.stdout + done.stderr).strip()

    def is_ready(self, index: int) -> bool:
        return self.ready(index)[0]

    def mark(self, index: int) -> str:
        """The role ready.sh's first-readiness gate passed in, or "" (not passed)."""
        done = subprocess.run(  # noqa: S603 - the test's own container
            ["docker", "exec", self.name(index), "cat", "/run/valkey/ready-role"],  # noqa: S607
            check=False, capture_output=True, text=True,
        )  # fmt: skip
        return done.stdout.strip() if done.returncode == 0 else ""

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

    def cli(self, index: int, *args: str, port: int = 6379, check: bool = True) -> str:
        return _run(
            "docker", "exec", "-e", f"REDISCLI_AUTH={self.password}", self.name(index),
            "valkey-cli", "-p", str(port), "--no-auth-warning", *args, check=check,
        )  # fmt: skip

    def connected_replicas(self, index: int) -> set[str]:
        """The hosts the server reports connected as its replicas (slave0:ip=<host>,port=...)."""
        info = self.cli(index, "info", "replication")
        return set(re.findall(r"^slave\d+:ip=([^,]+),", info.replace("\r", ""), re.MULTILINE))

    def known_replicas(self, asked: int) -> set[str]:
        """The replicas the pod's sentinel lists (their announced hosts)."""
        # One flat key, value list per replica: "name", <name>, "ip", <host>, "port", ...
        out = self.cli(asked, "SENTINEL", "replicas", "supportx", port=26379)
        fields = [line.strip() for line in out.splitlines()]
        return {value for key, value in pairwise(fields) if key == "ip"}

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


# Sentinel learns a master's replicas only from the master's INFO, which it asks every 10 s
# (sentinel.c's sentinel_info_period; the chart does not set it). A master lost before its
# sentinels saw the replicas there leaves them nothing to promote: every attempt aborts with
# -failover-abort-no-good-slave until the master is back, so no failover budget is enough.
# Since #284 pod 0 starts only once its peers answer, so the sentinels' first INFO of it often
# comes before the replicas connected, and a test could stop it inside the next 10 s (CI,
# 2026-11-10/11: three different tests out of time; neither surviving sentinel logged +slave).
SENTINEL_INFO_SECONDS = 10


def sentinels_know_the_replicas(valkeys: Valkeys) -> None:
    """The sentinels that must fail over (pods 1 and 2) both list pods 1 and 2 as replicas.
    One INFO period after the replicas connected, plus the runner margin of failover_seconds()."""
    wanted = {f"supportx-valkey-{i}.{HEADLESS}" for i in (1, 2)}
    for asked in (1, 2):
        _until(lambda a=asked: wanted <= valkeys.known_replicas(a), SENTINEL_INFO_SECONDS + 20)


def _pods(tmp_path: Path, request: pytest.FixtureRequest, *values: str) -> Iterator[Valkeys]:
    tmp_path.chmod(0o755)  # the containers' own user reads the scripts
    pods = 1 if "valkeyHa.replicas=1" in values else 3
    found = Valkeys(tmp_path, _scripts(tmp_path, *values), pods)
    _run("docker", "network", "create", found.network)
    failed_before = request.session.testsfailed
    try:
        for index in range(pods):
            found.start(index)
        yield found
    finally:
        if request.session.testsfailed > failed_before:
            # What each pod decided ("starting as master", "replica of ..."), for the CI log.
            for index in range(pods):
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

        for index in range(pods):
            found.stop(index)
        _run("docker", "network", "rm", found.network, check=False)


@pytest.fixture
def valkeys(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Valkeys]:
    yield from _pods(tmp_path, request)


@pytest.fixture
def lone(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Valkeys]:
    """One pod alone (valkeyHa.replicas 1): a master that never has a replica."""
    yield from _pods(tmp_path, request, "valkeyHa.replicas=1", "valkeyHa.quorum=1")


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
    sentinels_know_the_replicas(valkeys)  # else no failover can happen

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
    sentinels_know_the_replicas(valkeys)  # else no failover can happen

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
    sentinels_know_the_replicas(valkeys)  # else no failover can happen

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


def all_ready(valkeys: Valkeys) -> None:
    """Every pod passed its readiness probe once in its role (what a rolling update waits for)."""
    for index in range(3):
        _until(lambda i=index: valkeys.is_ready(i) and valkeys.mark(i) != "", START_SECONDS)


def test_a_master_is_ready_only_once_its_sentinel_lists_its_replicas(valkeys: Valkeys) -> None:
    """The fresh-start gap (lane B follow-up, 2026-11-11): a master Ready before the sentinels saw
    its replicas could be stopped with nothing to promote. Its sentinel is held back here, so it
    certainly does not know them yet: not ready, however healthy the server; then ready once the
    sentinel lists every connected replica, and only then."""
    for index in range(3):
        valkeys.stop(index)
    valkeys.start(0, sentinel=False)
    valkeys.start(1)
    valkeys.start(2)
    wanted = {f"supportx-valkey-{i}.{HEADLESS}" for i in (1, 2)}
    # Both replicas connected before pod 0's first probe (nothing here probes on its own): with
    # none connected it would rightly pass at once.
    _until(lambda: valkeys.connected_replicas(0) == wanted, START_SECONDS)
    assert valkeys.serving(0)
    ready, said = valkeys.ready(0)
    assert not ready
    assert "does not list these replicas yet" in said, said
    assert valkeys.mark(0) == ""

    valkeys.start_sentinel(0)
    deadline = time.monotonic() + SENTINEL_INFO_SECONDS + START_SECONDS
    while not valkeys.is_ready(0):
        assert time.monotonic() < deadline, "the master never became ready"
        time.sleep(0.2)
    # The sentinel's list only grows, so it lists them now if it did when the probe passed.
    assert wanted <= valkeys.known_replicas(0)
    assert valkeys.mark(0) == "master"


def test_a_replica_restarted_then_the_master_stopped_still_fails_over(valkeys: Valkeys) -> None:
    """A rolling update's step: a replica restarts and the next pod goes as soon as it is Ready.
    Only the readiness probe is waited for here (no sentinels_know_the_replicas): the restarted
    pod's new sentinel knows it, so whichever sentinel leads has a replica to promote."""
    _until(
        lambda: [valkeys.role(i) for i in range(3)] == ["master", "slave", "slave"], START_SECONDS
    )
    all_ready(valkeys)
    assert valkeys.cli(0, "set", "session:probe", "kept") == "OK"
    replicated(valkeys)

    valkeys.stop(2)
    valkeys.start(2)
    _until(lambda: valkeys.is_ready(2), START_SECONDS)
    assert valkeys.mark(2) == "slave"
    valkeys.stop(0)

    _until(
        lambda: valkeys.master(1) not in ("", f"supportx-valkey-0.{HEADLESS}"), failover_seconds()
    )
    promoted = int(valkeys.master(1).split(".")[0].rsplit("-", 1)[1])
    assert valkeys.role(promoted) == "master"
    assert valkeys.cli(promoted, "get", "session:probe") == "kept"
    # Promoted: its mark said "slave", so it gates again, as master, and passes.
    _until(
        lambda: valkeys.is_ready(promoted) and valkeys.mark(promoted) == "master",
        failover_seconds(),
    )


def test_a_lone_pod_without_replicas_is_ready(lone: Valkeys) -> None:
    _until(lambda: lone.role(0) == "master", START_SECONDS)
    _until(lambda: lone.is_ready(0), START_SECONDS)
    assert lone.mark(0) == "master"  # passed: never re-gated, so never flips over its sentinel
    assert lone.cli(0, "set", "first", "ok") == "OK"
    assert lone.is_ready(0)


def test_a_master_ready_before_its_replicas_stays_ready_without_its_sentinel(
    valkeys: Valkeys,
) -> None:
    """Lane B review, 2026-11-11: a master Ready with no replica yet is marked, so replicas
    connecting later and then a sentinel outage never turn it not ready (that flip would be the
    app's Valkey outage). Pods 1 and 2 are bare empty servers, so pod 0 starts as a fresh master
    with no replica; they become its replicas only after its first probe."""
    for index in range(3):
        valkeys.stop(index)
    for index in (1, 2):
        valkeys.start_plain(index)
        _until(lambda i=index: valkeys.cli(i, "ping") == "PONG", START_SECONDS)
    valkeys.start(0)
    _until(lambda: valkeys.role(0) == "master" and valkeys.is_ready(0), START_SECONDS)
    assert valkeys.connected_replicas(0) == set()
    assert valkeys.mark(0) == "master"

    wanted = {f"supportx-valkey-{i}.{HEADLESS}" for i in (1, 2)}
    for index in (1, 2):
        host = f"supportx-valkey-{index}.{HEADLESS}"
        valkeys.cli(index, "config", "set", "masterauth", valkeys.password)
        valkeys.cli(index, "config", "set", "replica-announce-ip", host)
        valkeys.cli(index, "replicaof", f"supportx-valkey-0.{HEADLESS}", "6379")
    _until(lambda: valkeys.connected_replicas(0) == wanted, START_SECONDS)
    valkeys.stop_sentinel(0)
    _until(lambda: not valkeys.sentinel_up(0), 10)
    for _ in range(3):  # several probe periods
        ready, said = valkeys.ready(0)
        assert ready, said
        assert valkeys.cli(0, "set", "session:probe", "kept") == "OK"
        time.sleep(2)
    assert valkeys.mark(0) == "master"


def test_a_ready_master_stays_ready_and_writable_without_its_sentinel(valkeys: Valkeys) -> None:
    """The coordinator, 2026-11-11: a sentinel blip must never become a Valkey outage. Once
    ready, only the server counts."""
    _until(
        lambda: [valkeys.role(i) for i in range(3)] == ["master", "slave", "slave"], START_SECONDS
    )
    all_ready(valkeys)
    assert valkeys.mark(0) == "master"

    valkeys.stop_sentinel(0)
    _until(lambda: not valkeys.sentinel_up(0), 10)
    for _ in range(3):  # several probe periods
        ready, said = valkeys.ready(0)
        assert ready, said
        assert valkeys.cli(0, "set", "session:probe", "kept") == "OK"
        time.sleep(2)
    assert valkeys.role(0) == "master"
