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

import json
import os
import re
import shutil
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


SHARED = [f"supportx_dev_{n}_data" for n in ("postgres", "valkey")]
OWN = [f"throwaway_{n}_data" for n in ("postgres", "valkey")]


def _config(name: str, volumes: list[str]) -> str:
    return json.dumps({"name": name, "volumes": {v: {"name": v} for v in volumes}})


@pytest.fixture
def stub_docker(tmp_path: Path) -> Path:
    """A `docker` on PATH: answers `config --format json` with $STUB_CONFIG, records the rest."""
    stub = tmp_path / "bin" / "docker"
    stub.parent.mkdir()
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ " $* " == *" config --format json "* ]]; then\n'
        f'  echo "$@" >> {tmp_path / "config_calls"}\n'
        '  [[ -n "${STUB_FAIL:-}" ]] && { echo "bad compose file" >&2; exit 1; }\n'
        '  printf "%s" "$STUB_CONFIG"; exit 0\n'
        "fi\n"
        f'echo "$@" >> {tmp_path / "calls"}\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return tmp_path


def _guard(stub: Path, *args: str, config: str, **env: str) -> tuple[int, str, str, str]:
    dropped = {"COMPOSE_PROJECT_NAME", "SUPPORTX_VOLUME_PREFIX"}
    clean = {k: v for k, v in os.environ.items() if k not in dropped}
    run = subprocess.run(  # noqa: S603 - our own script, fixed arguments
        [str(GUARD), *args],
        env={**clean, "PATH": f"{stub / 'bin'}:{clean.get('PATH', '')}", "STUB_CONFIG": config,
             **env},
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip
    return run.returncode, _read(stub / "calls"), _read(stub / "config_calls"), run.stderr


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


@pytest.mark.parametrize(
    ("config", "reason"),
    [
        # another project on the shared volumes (the incident), or even one of them
        (_config("throwaway", SHARED), "would use the shared dev stack volumes"),
        (_config("throwaway", [*OWN, SHARED[0]]), "would use the shared dev stack volumes"),
        # the shared project on someone else's volumes
        (_config("supportx-dev", OWN), "the shared dev stack keeps its own volumes"),
    ],
)
def test_the_guard_refuses_a_project_on_someone_elses_volumes(
    stub_docker: Path, config: str, reason: str
) -> None:
    code, calls, _, errors = _guard(stub_docker, "up", "-d", config=config)
    assert code == 3
    assert reason in errors, errors  # refused for this reason, not any other
    assert calls == "", "docker compose ran although the guard refused"


@pytest.mark.parametrize("config", [_config("supportx-dev", SHARED), _config("throwaway", OWN)])
def test_the_guard_passes_a_project_on_its_own_volumes(stub_docker: Path, config: str) -> None:
    code, calls, _, errors = _guard(stub_docker, "up", "-d", config=config)
    assert code == 0, errors
    assert calls.startswith("compose --project-directory ")
    assert calls.rstrip().endswith("up -d")


def test_the_guard_asks_compose_with_the_same_global_options(stub_docker: Path) -> None:
    """The project and prefix may come from --env-file or .env: compose resolves them itself."""
    code, _, asked, errors = _guard(
        stub_docker, "--env-file", "x.env", "-p", "p", "run", "-p", "5432:5432", "db",
        config=_config("p", OWN),
    )  # fmt: skip
    assert code == 0, errors
    assert asked.rstrip().endswith("--env-file x.env -p p config --format json")
    assert "5432" not in asked  # `run -p` is a port, not a project


def test_the_guard_refuses_when_compose_cannot_resolve_the_project(stub_docker: Path) -> None:
    code, calls, _, errors = _guard(stub_docker, "up", "-d", config="", STUB_FAIL="1")
    assert code == 3
    assert "could not resolve the project" in errors
    assert calls == ""


def _required_env(tmp_path: Path, extra: str = "") -> Path:
    names = sorted(
        set(re.findall(r"\$\{([A-Z0-9_]+):\?", COMPOSE_FILE.read_text(encoding="utf-8")))
    )
    env = tmp_path / "test.env"
    env.write_text("".join(f"{n}=dummy\n" for n in names) + extra, encoding="utf-8")
    return env


@pytest.mark.skipif(shutil.which("docker") is None, reason="needs docker (compose config only)")
@pytest.mark.parametrize(
    ("extra", "code"),
    [
        ("COMPOSE_PROJECT_NAME=supportx-e2e-c\n", 3),  # the incident: the project from an env file
        ("COMPOSE_PROJECT_NAME=supportx-e2e-c\nSUPPORTX_VOLUME_PREFIX=e2e_c\n", 0),
        ("", 0),  # the shared stack itself
        ("SUPPORTX_VOLUME_PREFIX=e2e_c\n", 3),  # the shared project on foreign volumes
    ],
)
def test_real_compose_resolves_the_env_file_and_the_guard_follows(
    tmp_path: Path, extra: str, code: int
) -> None:
    """Real `docker compose config` (it only renders): nothing is started."""
    dropped = {"COMPOSE_PROJECT_NAME", "SUPPORTX_VOLUME_PREFIX"}
    env = {k: v for k, v in os.environ.items() if k not in dropped}
    run = subprocess.run(  # noqa: S603 - our own script, fixed arguments
        [str(GUARD), "--env-file", str(_required_env(tmp_path, extra)), "config", "--quiet"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == code, run.stderr


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


@pytest.mark.usefixtures("stack_env")
def test_the_valkey_nats_and_minio_test_fallbacks_need_the_opt_in_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tests/db's valkey_url() (every DB test's Valkey, through shared_world), NATS and MinIO."""
    from tests.db.test_audit_exports import s3_config  # noqa: PLC0415 - the helpers under test
    from tests.db.test_rate_limit import valkey_url  # noqa: PLC0415
    from tests.events.conftest import nats_url  # noqa: PLC0415

    db_testing.STACK_ENV.write_text(
        db_testing.STACK_ENV.read_text(encoding="utf-8")
        + "VALKEY_PASSWORD=v\nVALKEY_PORT=26379\nNATS_PORT=24222\n"
        "MINIO_API_PORT=29000\nMINIO_ROOT_USER=u\nMINIO_ROOT_PASSWORD=p\n",
        encoding="utf-8",
    )
    for name in ("SUPPORTX_TEST_VALKEY_URL", "SUPPORTX_TEST_NATS_URL", "SUPPORTX_TEST_S3_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    assert (valkey_url(), nats_url(), s3_config()) == (None, None, None)
    monkeypatch.setenv(db_testing.ALLOW_DEV_STACK, "1")
    assert valkey_url() == "valkey://:v@127.0.0.1:26379/0"
    assert nats_url() == "nats://127.0.0.1:24222"
    assert s3_config() == ("http://127.0.0.1:29000", "u", "p")
    # An explicit throwaway always wins.
    monkeypatch.setenv("SUPPORTX_TEST_VALKEY_URL", "valkey://127.0.0.1:56391/0")
    assert valkey_url() == "valkey://127.0.0.1:56391/0"
