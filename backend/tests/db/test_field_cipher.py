"""Field encryption on the tenant's data keys (ADR-050; WP-057 S3a; lane B's conditions).

Real PostgreSQL as the application role, files' `tenant_data_keys` and installation key ring:
- a value opens only with its purpose, its record and field, in its tenant;
- what does not open is None (a security event), never an error page; a missing installation
  key is a 503 instead, so good data is never called unreadable by a configuration fault;
- a rotated data key keeps opening what it sealed, and new values use the new one;
- purposes are declared once.
"""

import uuid

import asyncpg
import pytest
from pydantic import SecretStr

from app.core.tenancy import TenantContext
from app.shared.crypto import from_text, key_id_of
from app.shared.fields import (
    Binding,
    DataKeyCache,
    FieldKeysUnavailable,
    PurposeError,
    destroy_tenant_keys,
    field_cipher,
    field_cipher_for,
    field_keys,
    purpose,
)
from app.shared.fields.tests.test_cache import MemoryGenerations
from app.shared.files.keyring import KeyRing
from app.shared.files.service.core import rotate_data_key
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

SECRET = purpose("tests", "webhook_header")
OTHER = purpose("tests", "draft")
RING = KeyRing.parse(KeyRing.generate("k1"))
RECORD = uuid.uuid4()
HERE = Binding("workflows", RECORD, "headers.authorization")


async def _seal(world: World, value: str, binding: Binding = HERE, ring: KeyRing = RING) -> str:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        return await field_cipher(session, ring).seal(SECRET, binding, value)


async def _open(
    world: World,
    text: str,
    *,
    tenant: uuid.UUID | None = None,
    purpose_: str = SECRET,
    binding: Binding = HERE,
    ring: KeyRing | None = RING,
) -> str | None:
    context = TenantContext(tenant or world.a.tenant)
    async with world.app.state.db.tenant_session(context) as session:
        return await field_cipher(session, ring).open(purpose_, binding, text)


async def test_a_value_opens_only_where_it_was_sealed(world: World) -> None:
    text = await _seal(world, "Bearer s3cr3t")
    assert text.startswith("sx2:")
    assert "s3cr3t" not in text
    assert await _open(world, text) == "Bearer s3cr3t"
    # Another purpose, record, field or tenant: it does not open (a bad tag, or no such key).
    assert await _open(world, text, purpose_=OTHER) is None
    assert await _open(world, text, binding=Binding("workflows", uuid.uuid4(), HERE.field)) is None
    assert await _open(world, text, binding=Binding("workflows", RECORD, "headers.x")) is None
    assert await _open(world, text, tenant=world.b.tenant) is None


async def test_changed_or_malformed_text_is_unreadable_not_an_error(world: World) -> None:
    text = await _seal(world, "value")
    flipped = text[:-2] + ("A" if text[-2] != "A" else "B") + text[-1]
    assert await _open(world, flipped) is None
    for junk in ("", "plain text", "sx2:!!!", "sx2:AA"):
        assert await _open(world, junk) is None


async def test_a_missing_installation_key_is_a_503_not_unreadable_data(world: World) -> None:
    text = await _seal(world, "value")
    other_ring = KeyRing.parse(KeyRing.generate("k9"))  # the Secret replaced by mistake
    with pytest.raises(FieldKeysUnavailable):
        await _open(world, text, ring=other_ring)
    with pytest.raises(FieldKeysUnavailable):
        await _open(world, text, ring=None)
    with pytest.raises(FieldKeysUnavailable):
        async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
            await field_cipher(session, None).seal(SECRET, HERE, "value")


def _key_of(text: str) -> str | None:
    blob = from_text(text)
    return None if blob is None else key_id_of(blob)


async def test_a_rotated_data_key_still_opens_what_it_sealed(world: World) -> None:
    before = await _seal(world, "old value")
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        await rotate_data_key(session, RING)
    after = await _seal(world, "new value")
    assert _key_of(before) != _key_of(after)  # the new value names the new data key
    assert await _open(world, before) == "old value"
    assert await _open(world, after) == "new value"


def test_purposes_are_declared_once_and_well_formed() -> None:
    with pytest.raises(PurposeError):
        purpose("tests", "webhook_header")  # declared above
    for module, what in (("Tests", "x"), ("tests", "x y"), ("", "x"), ("tests", "")):
        with pytest.raises(PurposeError):
            purpose(module, what)


async def test_undeclared_purposes_and_empty_bindings_are_refused(world: World) -> None:
    with pytest.raises(ValueError, match="never declared"):
        async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
            await field_cipher(session, RING).seal("field.tests.nobody", HERE, "x")
    with pytest.raises(ValueError, match="bound to"):
        await _seal(world, "x", binding=Binding("", RECORD, "f"))


async def test_erasure_empties_every_cache_at_once(world: World) -> None:
    """Lane B: crypto-shredding is immediate even in a process that cached the data key."""
    generations = MemoryGenerations()
    cache = DataKeyCache(generations)
    text = await _seal(world, "kept until erased")
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        assert await field_cipher(session, RING, cache).open(SECRET, HERE, text) is not None
    assert len(cache) == 1  # cached in this process

    async def destroy() -> None:
        conn = await asyncpg.connect(world.db.admin_url)
        try:  # the tenant erasure job's step: the data keys go (superuser: tenant named)
            await conn.execute("DELETE FROM tenant_data_keys WHERE tenant_id = $1", world.a.tenant)
        finally:
            await conn.close()

    await destroy_tenant_keys(generations, world.a.tenant, destroy)
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        assert await field_cipher(session, RING, cache).open(SECRET, HERE, text) is None


async def test_without_the_generation_a_cached_key_would_outlive_its_erasure(world: World) -> None:
    """Why the bump is needed: a plain delete leaves this process's cached key working."""
    generations = MemoryGenerations()
    cache = DataKeyCache(generations)
    text = await _seal(world, "the control case")
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        cipher = field_cipher(session, RING, cache)
        assert await cipher.open(SECRET, HERE, text) == "the control case"
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        await conn.execute("DELETE FROM tenant_data_keys WHERE tenant_id = $1", world.a.tenant)
    finally:
        await conn.close()
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        assert await field_cipher(session, RING, cache).open(SECRET, HERE, text) is not None


async def test_field_cipher_for_takes_the_keys_from_the_settings(world: World) -> None:
    """Lane A: a module needs only this one call; the key ring is chosen in one place."""
    settings = world.app.state.settings.model_copy(
        update={"files_keys": SecretStr(KeyRing.generate("k1")), "valkey_url": None}
    )
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        cipher = field_cipher_for(session, settings)
        text = await cipher.seal(SECRET, HERE, "from settings")
        assert await cipher.open(SECRET, HERE, text) == "from settings"
    assert field_keys(settings) is field_keys(settings)  # parsed once per process
    without = settings.model_copy(update={"files_keys": None})
    with pytest.raises(FieldKeysUnavailable):
        async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
            await field_cipher_for(session, without).seal(SECRET, HERE, "x")
