"""Audit exports and the offline verifier (WP-018; REQ-AUD-009) on real S3-compatible storage.

Storage: SUPPORTX_TEST_S3_ENDPOINT (+ _ACCESS_KEY, _SECRET_KEY; CI runs SeaweedFS), else the dev
stack's MinIO. Each test uses its own bucket and removes it afterwards. Skips locally without
storage; SUPPORTX_REQUIRE_S3_TESTS=1 makes that a failure.
"""

import asyncio
import hashlib
import json
import os
import uuid
import zipfile
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import aioboto3
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext
from app.main import create_app
from app.modules.audit.infra.signing import LocalSigner, new_key_config, trusted_keys
from app.modules.audit.service.exports import build_export, expire_exports
from app.modules.audit.service.integrity import anchor, seal
from app.modules.audit.tools.verify_export import Broken, verify
from app.shared.clock import FrozenClock, system_clock
from app.shared.storage import S3Storage, StorageUnavailable
from conftest import make_settings
from tests.db.test_access_api import fake_session
from tests.db.test_incidents_api import World, make_org
from tests.db.test_rate_limit import valkey_url
from tooling import db_testing
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]

SIGNER = LocalSigner.from_config(new_key_config("export-key"))
TRUSTED = trusted_keys("", SIGNER)


def s3_config() -> tuple[str, str, str] | None:
    if endpoint := os.environ.get("SUPPORTX_TEST_S3_ENDPOINT"):
        return (
            endpoint,
            os.environ.get("SUPPORTX_TEST_S3_ACCESS_KEY", "any"),
            os.environ.get("SUPPORTX_TEST_S3_SECRET_KEY", "any"),
        )
    if db_testing.STACK_ENV.is_file():
        env = db_testing._read_env_file(db_testing.STACK_ENV)  # noqa: SLF001 - shared test helper
        return (
            f"http://127.0.0.1:{env.get('MINIO_API_PORT', '29000')}",
            env["MINIO_ROOT_USER"],
            env["MINIO_ROOT_PASSWORD"],
        )
    return None


@pytest_asyncio.fixture
async def storage() -> AsyncIterator[S3Storage]:
    """A fresh bucket on reachable storage, removed with everything in it afterwards."""
    endpoint, access_key, secret_key = s3_config() or ("http://127.0.0.1:1", "x", "x")
    bucket = f"sx-test-{uuid.uuid4().hex[:12]}"
    store = S3Storage(endpoint, "us-east-1", access_key, secret_key, bucket, 5)
    try:
        await store.ensure_bucket()
    except StorageUnavailable:
        reason = "S3 storage is not reachable (make dev-up / SUPPORTX_TEST_S3_ENDPOINT)"
        if os.environ.get("SUPPORTX_REQUIRE_S3_TESTS") == "1":
            pytest.fail(f"S3 tests are required here but {reason}")
        pytest.skip(reason)
    yield store
    session = aioboto3.Session()
    async with session.client(
        "s3",
        endpoint_url=store.endpoint,
        region_name=store.region,
        aws_access_key_id=store.access_key,
        aws_secret_access_key=store.secret_key,
    ) as client:
        listed = await client.list_objects_v2(Bucket=bucket)
        for item in listed.get("Contents", []):
            await client.delete_object(Bucket=bucket, Key=item["Key"])
        await client.delete_bucket(Bucket=bucket)


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase, storage: S3Storage) -> AsyncIterator[World]:
    url = valkey_url()
    if url is None:
        pytest.skip("Valkey is not configured")
    app = create_app(
        make_settings(
            database_url=migrated_db.app_url,
            valkey_url=url,
            object_storage_endpoint=storage.endpoint,
            object_storage_access_key=storage.access_key,
            object_storage_secret_key=storage.secret_key,
            object_storage_bucket=storage.bucket,
        )
    )
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            w = World(client, migrated_db, app, a=None, b=None)  # type: ignore[arg-type]  # set below
            w.a = await make_org(w, "Alpha")
            w.b = await make_org(w, "Beta")
            yield w


async def _prepare(world: World, org: Any) -> None:  # noqa: ANN401 - Org
    for i in range(3):
        created = await world.call(
            "POST", "/roles", org, org.admin, json={"name": f"Export {i}", "permissions": []}
        )
        assert created.status_code == 201, created.text
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        await seal(session, 500)
        await anchor(session, SIGNER, every=timedelta(0))


async def _export(world: World, org: Any, storage: S3Storage, **body: Any) -> dict[str, Any]:  # noqa: ANN401 - Org / JSON
    requested = await world.call("POST", "/audit/exports", org, org.admin, json=body)
    assert requested.status_code == 202, requested.text
    export_id = uuid.UUID(requested.json()["id"])
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        await build_export(session, export_id, storage=storage, signer=SIGNER, trusted_keys=TRUSTED)
    listed = (await world.call("GET", "/audit/exports", org, org.admin)).json()
    return next(e for e in listed if e["id"] == str(export_id))


async def _download(world: World, org: Any, export: dict[str, Any], path: Path) -> Path:  # noqa: ANN401 - Org
    response = await world.call("GET", f"/audit/exports/{export['id']}/download", org, org.admin)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    await asyncio.to_thread(path.write_bytes, response.content)
    return path


def _rewrite(source: Path, target: Path, change: Any) -> Path:  # noqa: ANN401 - callable
    """Copy the zip, letting `change(name, bytes)` alter members (a throwaway copy)."""
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as out:
        for name in src.namelist():
            out.writestr(name, change(name, src.read(name)))
    return target


async def test_req_aud_009_ac1_an_export_verifies_with_the_published_verifier(
    world: World, storage: S3Storage, tmp_path: Path
) -> None:
    a = world.a
    await _prepare(world, a)
    export = await _export(world, a, storage, format="jsonl")
    assert (export["status"], export["verification"]) == ("ready", "passed")
    path = await _download(world, a, export, tmp_path / "export.zip")
    summary = verify(str(path))
    assert summary.startswith(f"verified {export['entries']} entries (complete)")
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "manifest.sig",
            "audit.jsonl",
            "verify_export.py",
            "README.txt",
        }
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["anchors"]
    assert manifest["trusted_keys"] == {"export-key": SIGNER.public_key.hex()}
    downloads = (
        await world.call("GET", "/audit/entries?action=audit.export_downloaded", a, a.admin)
    ).json()
    assert [e["object_id"] for e in downloads["items"]] == [export["id"]]


async def test_req_aud_009_ac2_removing_or_changing_a_line_is_caught(
    world: World, storage: S3Storage, tmp_path: Path
) -> None:
    a = world.a
    await _prepare(world, a)
    path = await _download(world, a, await _export(world, a, storage), tmp_path / "e.zip")

    def drop_line(name: str, data: bytes) -> bytes:
        if name != "audit.jsonl":
            return data
        lines = data.decode().splitlines(keepends=True)
        return "".join(lines[:1] + lines[2:]).encode()

    with pytest.raises(Broken, match="data file was changed"):
        verify(str(_rewrite(path, tmp_path / "dropped.zip", drop_line)))

    # A smarter forger also fixes the file's SHA-256 in the manifest: the entry hash, the
    # chain and the manifest signature still catch it.
    with zipfile.ZipFile(path) as archive:
        lines = archive.read("audit.jsonl").decode().splitlines()
        manifest = json.loads(archive.read("manifest.json"))
    record = json.loads(lines[1])
    record["entry"]["outcome"] = "refused"
    lines[1] = json.dumps(record, sort_keys=True)
    forged = ("\n".join(lines) + "\n").encode()
    manifest["data_sha256"] = hashlib.sha256(forged).hexdigest()

    def replace(name: str, data: bytes) -> bytes:
        if name == "audit.jsonl":
            return forged
        if name == "manifest.json":
            return json.dumps(manifest, sort_keys=True, indent=2).encode()
        return data

    with pytest.raises(Broken, match="was changed"):
        verify(str(_rewrite(path, tmp_path / "forged.zip", replace)))


async def test_csv_and_filtered_exports(world: World, storage: S3Storage, tmp_path: Path) -> None:
    a = world.a
    await _prepare(world, a)
    csv_export = await _export(world, a, storage, format="csv")
    assert verify(str(await _download(world, a, csv_export, tmp_path / "c.zip"))).startswith(
        "verified"
    )
    filtered = await _export(world, a, storage, filters={"action": "role.created"})
    summary = verify(str(await _download(world, a, filtered, tmp_path / "f.zip")))
    assert "(filtered)" in summary
    assert filtered["entries"] >= 3


async def test_exports_fail_visibly_without_or_with_unreachable_storage(
    world: World, storage: S3Storage, migrated_db: ThrowawayDatabase
) -> None:
    a = world.a
    requested = await world.call("POST", "/audit/exports", a, a.admin, json={})
    export_id = uuid.UUID(requested.json()["id"])
    down = S3Storage("http://127.0.0.1:1", "us-east-1", "x", "x", storage.bucket, 1)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        row = await build_export(
            session, export_id, storage=down, signer=SIGNER, trusted_keys=TRUSTED
        )
    assert row is not None
    assert (row.status, row.problem) == ("failed", "storage_unavailable")
    listed = (await world.call("GET", "/audit/exports", a, a.admin)).json()
    assert next(e for e in listed if e["id"] == str(export_id))["problem"] == "storage_unavailable"
    # No storage configured at all: the request is refused at once.
    bare = create_app(make_settings(database_url=migrated_db.app_url, valkey_url=valkey_url()))
    async with bare.router.lifespan_context(bare):
        setattr(bare.state, SESSION_RESOLVER_STATE, fake_session)
        async with AsyncClient(transport=ASGITransport(app=bare), base_url="http://test") as client:
            refused = await client.post(
                "/api/v1/audit/exports",
                json={},
                headers={"X-Test-Tenant": str(a.tenant), "X-Test-User": str(a.admin)},
            )
    assert (refused.status_code, refused.json()["code"]) == (503, "storage_not_configured")


async def test_exports_expire_after_seven_days(world: World, storage: S3Storage) -> None:
    a = world.a
    await _prepare(world, a)
    export = await _export(world, a, storage)
    later = FrozenClock(system_clock.now() + timedelta(days=8))
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await expire_exports(session, storage, later) == 1
    gone = await world.call("GET", f"/audit/exports/{export['id']}/download", a, a.admin)
    assert (gone.status_code, gone.json()["code"]) == (409, "audit_export_not_ready")
    assert await storage.get(f"audit/exports/{a.tenant}/{export['id']}.zip") is None


async def test_only_export_holders_may_export(world: World) -> None:
    a = world.a
    assert (await world.call("POST", "/audit/exports", a, a.tech_a, json={})).status_code == 404
    assert (await world.call("GET", "/audit/exports", a, a.lead)).status_code == 404
