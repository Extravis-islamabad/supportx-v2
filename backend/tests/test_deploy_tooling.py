"""The deploy-time database step and the init-container wait (WP-014)."""

import asyncio
import secrets
from typing import Any

import asyncpg
import httpx
import pytest

from tooling import db_testing, wait_for_job
from tooling.db_bootstrap import TEST_DATABASE_PREFIX, with_credentials, with_database
from tooling.deploy_migrate import Action, DeployConfig, migrate, plan
from tooling.wait_for_job import JobState, job_state

# --- what the migrate step decides ---------------------------------------------------------------


def test_plan_upgrades_current_and_leaves_newer_databases_alone() -> None:
    known = {"0001", "0002", "0003"}
    assert plan(None, known, "0003") is Action.UPGRADE  # empty database
    assert plan("0002", known, "0003") is Action.UPGRADE
    assert plan("0003", known, "0003") is Action.CURRENT
    # A rollback to an older release: the database is ahead of this code. Never downgrade.
    assert plan("0004", known, "0003") is Action.NEWER


def test_deploy_config_without_admin_skips_the_bootstrap() -> None:
    config = DeployConfig.from_env({"SUPPORTX_MIGRATION_DATABASE_URL": "postgresql://m@db/x"})
    assert (config.admin_url, config.passwords, config.database) == (None, None, "supportx")
    with pytest.raises(KeyError):  # an admin URL without the role passwords is a config error
        DeployConfig.from_env(
            {
                "SUPPORTX_MIGRATION_DATABASE_URL": "postgresql://m@db/x",
                "SUPPORTX_DEPLOY_ADMIN_URL": "postgresql://a@db/postgres",
            }
        )


@pytest.mark.db
async def test_migrate_bootstraps_upgrades_and_is_rerunnable(
    db_config: db_testing.DbTestConfig,
) -> None:
    name = f"{TEST_DATABASE_PREFIX}{secrets.token_hex(6)}"
    in_db = with_database(db_config.admin_url, name)
    config = DeployConfig(
        migrator_url=with_credentials(in_db, "supportx_migrator", db_config.migrator_password),
        admin_url=db_config.admin_url,
        database=name,
        passwords=db_config.passwords,
        wait_seconds=5,
    )
    try:
        assert await migrate(config) is Action.UPGRADE
        assert await migrate(config) is Action.CURRENT  # every revision's Job may run again
        # A newer release migrated it (simulated): an older Job leaves it alone.
        conn = await asyncpg.connect(in_db)
        try:
            await conn.execute("UPDATE alembic_version SET version_num = 'from_the_future'")
            assert await migrate(config) is Action.NEWER
            assert await conn.fetchval("SELECT version_num FROM alembic_version") == (
                "from_the_future"
            )
        finally:
            await conn.close()
    finally:
        await asyncio.to_thread(db_testing.destroy, db_config, db_testing.describe(db_config, name))


# --- the init container's wait -------------------------------------------------------------------


def job(**status: Any) -> dict[str, Any]:  # noqa: ANN401 - Kubernetes JSON
    return {"kind": "Job", "status": status}


def test_job_state_reads_conditions_and_counters() -> None:
    assert job_state(None) is JobState.GONE
    assert job_state(job()) is JobState.RUNNING
    assert job_state(job(active=1)) is JobState.RUNNING
    assert job_state(job(succeeded=1)) is JobState.SUCCEEDED
    assert job_state(job(conditions=[{"type": "Complete", "status": "True"}])) is (
        JobState.SUCCEEDED
    )
    assert job_state(job(conditions=[{"type": "Failed", "status": "True"}])) is JobState.FAILED
    assert job_state(job(conditions=[{"type": "Failed", "status": "False"}])) is JobState.RUNNING


def client_for(*replies: dict[str, Any] | None) -> tuple[httpx.Client, list[str]]:
    paths: list[str] = []
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx.Response(404) if reply is None else httpx.Response(200, json=reply)

    return httpx.Client(transport=httpx.MockTransport(handler)), paths


def test_wait_polls_until_the_job_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wait_for_job, "POLL_SECONDS", 0)
    client, paths = client_for(job(active=1), job(active=1), job(succeeded=1))
    assert wait_for_job.wait(client, "supportx", "supportx-migrate-3", 5) is JobState.SUCCEEDED
    assert paths[0] == "/apis/batch/v1/namespaces/supportx/jobs/supportx-migrate-3"
    assert len(paths) == 3


def test_wait_reports_a_failed_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wait_for_job, "POLL_SECONDS", 0)
    client, _ = client_for(job(conditions=[{"type": "Failed", "status": "True"}]))
    assert wait_for_job.wait(client, "ns", "j", 5) is JobState.FAILED


def test_a_job_replaced_by_a_newer_release_lets_the_pod_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wait_for_job, "POLL_SECONDS", 0)
    monkeypatch.setattr(wait_for_job, "GONE_GRACE_SECONDS", 0)
    client, _ = client_for(None)
    assert wait_for_job.wait(client, "ns", "j", 5) is JobState.GONE


def test_a_job_that_never_finishes_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wait_for_job, "POLL_SECONDS", 0)
    client, _ = client_for(job(active=1))
    assert wait_for_job.wait(client, "ns", "j", 0.05) is JobState.RUNNING
