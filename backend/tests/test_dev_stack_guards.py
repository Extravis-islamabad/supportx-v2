"""Guards that keep anything but the shared dev stack off its data (the 2026-11-20 incident).

A "throwaway" compose stack under another project name mounted the shared stack's named volumes,
so two PostgreSQL servers ran on one data directory; and local DB tests fell back to the shared
stack's PostgreSQL by default. These tests pin both fixes without Docker:

- the compose file's volume names carry SUPPORTX_VOLUME_PREFIX, whose default keeps exactly the
  shared stack's names (nothing orphaned);
- deploy/compose/scripts/compose.sh refuses a non-default project with the default prefix (and
  the shared project with a foreign prefix), and passes everything else to `docker compose`;
- tooling.db_testing falls back to the shared stack only when asked to.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

from tooling import db_testing

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "deploy" / "compose" / "docker-compose.yml"
GUARD = ROOT / "deploy" / "compose" / "scripts" / "compose.sh"
# The shared stack's volume names before the prefix existed: they must not change.
SHARED_VOLUMES = {
    f"supportx_dev_{name}_data"
    for name in (
        "postgres",
        "valkey",
        "nats",
        "minio",
        "mailpit",
        "opensearch",
        "clickhouse",
        "clamav",
    )
}


def test_every_volume_name_takes_the_prefix_and_defaults_to_the_shared_names() -> None:
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    top = text[text.index("\nvolumes:\n") :]
    names = re.findall(r"^    name: (.+)$", top, flags=re.MULTILINE)
    pattern = re.compile(r"^\$\{SUPPORTX_VOLUME_PREFIX:-supportx_dev\}_(\w+)_data$")
    assert names, "no named volumes found"
    assert all(pattern.match(n) for n in names), names
    defaults = {pattern.sub(r"supportx_dev_\1_data", n) for n in names}
    assert defaults == SHARED_VOLUMES


@pytest.fixture
def stub_docker(tmp_path: Path) -> Path:
    """A `docker` on PATH that only records how it was called."""
    calls = tmp_path / "calls"
    stub = tmp_path / "bin" / "docker"
    stub.parent.mkdir()
    stub.write_text(f'#!/usr/bin/env bash\necho "$@" >> {calls}\n', encoding="utf-8")
    stub.chmod(0o755)
    return tmp_path


def _guard(stub: Path, *args: str, **env: str) -> tuple[int, str]:
    dropped = {"COMPOSE_PROJECT_NAME", "SUPPORTX_VOLUME_PREFIX"}
    clean = {k: v for k, v in os.environ.items() if k not in dropped}
    run = subprocess.run(  # noqa: S603 - our own script, fixed arguments
        [str(GUARD), *args],
        env={**clean, "PATH": f"{stub / 'bin'}:{clean.get('PATH', '')}", **env},
        capture_output=True,
        text=True,
        check=False,
    )
    calls = stub / "calls"
    return run.returncode, calls.read_text(encoding="utf-8") if calls.exists() else ""


@pytest.mark.parametrize(
    ("args", "env"),
    [
        (("-p", "throwaway"), {}),
        (("--project-name", "throwaway"), {}),
        (("--project-name=throwaway",), {}),
        (("-pthrowaway",), {}),
        ((), {"COMPOSE_PROJECT_NAME": "throwaway"}),
        (("-p", "throwaway"), {"SUPPORTX_VOLUME_PREFIX": "supportx_dev"}),
        ((), {"SUPPORTX_VOLUME_PREFIX": "throwaway"}),  # the shared project, foreign volumes
    ],
)
def test_the_guard_refuses_a_project_on_someone_elses_volumes(
    stub_docker: Path, args: tuple[str, ...], env: dict[str, str]
) -> None:
    code, calls = _guard(stub_docker, *args, "up", "-d", **env)
    assert code == 3
    assert calls == "", "docker compose ran although the guard refused"


@pytest.mark.parametrize(
    ("args", "env"),
    [
        ((), {}),  # the shared stack itself (make dev-up)
        (("-p", "throwaway"), {"SUPPORTX_VOLUME_PREFIX": "throwaway"}),
        ((), {"COMPOSE_PROJECT_NAME": "throwaway", "SUPPORTX_VOLUME_PREFIX": "throwaway"}),
    ],
)
def test_the_guard_passes_a_project_on_its_own_volumes(
    stub_docker: Path, args: tuple[str, ...], env: dict[str, str]
) -> None:
    code, calls = _guard(stub_docker, *args, "up", "-d", **env)
    assert code == 0
    assert calls.startswith("compose --project-directory ")
    assert calls.rstrip().endswith("up -d")


def test_the_makefile_goes_through_the_guard() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "COMPOSE := $(DEV_DIR)/scripts/compose.sh" in makefile
    assert "docker compose --project-directory $(DEV_DIR)" not in makefile


@pytest.fixture
def stack_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "POSTGRES_SUPERUSER=postgres\nPOSTGRES_SUPERUSER_PASSWORD=pw\nPOSTGRES_PORT=25432\n"
        "SUPPORTX_APP_PASSWORD=a\nSUPPORTX_MIGRATOR_PASSWORD=m\nSUPPORTX_RELAY_PASSWORD=r\n"
        "PGBOUNCER_PORT=26432\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(db_testing, "STACK_ENV", env)
    for name in ("SUPPORTX_TEST_ADMIN_URL", db_testing.ALLOW_DEV_STACK):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("stack_env")
def test_db_tests_never_fall_back_to_the_shared_stack_unasked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert db_testing.load_config() is None
    assert db_testing.dev_stack_env() is None
    found = db_testing.load_config(allow_dev_stack=True)  # make db-bootstrap
    assert found is not None
    assert found.admin_url.endswith("@127.0.0.1:25432/postgres")
    monkeypatch.setenv(db_testing.ALLOW_DEV_STACK, "1")
    assert db_testing.load_config() is not None
    assert db_testing.dev_stack_env() is not None


@pytest.mark.usefixtures("stack_env")
def test_an_explicit_test_database_always_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in (
        ("SUPPORTX_TEST_ADMIN_URL", "postgresql://postgres:x@127.0.0.1:55447/postgres"),
        ("SUPPORTX_TEST_APP_PASSWORD", "a"),
        ("SUPPORTX_TEST_MIGRATOR_PASSWORD", "m"),
        ("SUPPORTX_TEST_RELAY_PASSWORD", "r"),
    ):
        monkeypatch.setenv(name, value)
    found = db_testing.load_config()
    assert found is not None
    assert found.admin_url.endswith(":55447/postgres")
