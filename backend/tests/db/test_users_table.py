"""users: tenant isolation (RLS) and created_by/updated_by stamped from app.user_id."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.database import Database
from app.core.tenancy import TenantContext

pytestmark = pytest.mark.db

INSERT = text(
    "INSERT INTO users (id, tenant_id, external_subject, email, display_name, first_name,"
    " user_type) VALUES (:id, :tenant, :sub, :email, 'Someone', 'Someone', 'technician')"
)


async def add_user(db: Database, tenant: uuid.UUID, actor: uuid.UUID | None = None) -> uuid.UUID:
    user_id = uuid.uuid4()
    async with db.tenant_session(TenantContext(tenant, actor)) as session:
        await session.execute(
            INSERT,
            {"id": user_id, "tenant": tenant, "sub": str(user_id), "email": f"{user_id}@t.test"},
        )
    return user_id


async def test_users_are_isolated_per_tenant(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = tenant_pair
    await add_user(app_db, a)
    b_user = await add_user(app_db, b)
    async with app_db.tenant_session(TenantContext(a)) as session:
        tenants_seen = (
            (await session.execute(text("SELECT DISTINCT tenant_id FROM users"))).scalars().all()
        )
        hidden = await session.scalar(
            text("SELECT count(*) FROM users WHERE id = :id"), {"id": b_user}
        )
        renamed = await session.execute(
            text("UPDATE users SET display_name = 'x' WHERE id = :id"), {"id": b_user}
        )
    assert tenants_seen == [a]
    assert hidden == 0
    assert renamed.rowcount == 0  # type: ignore[attr-defined]  # CursorResult at runtime
    with pytest.raises(ProgrammingError, match="row-level security"):
        await _insert_for(app_db, a, b)  # tenant A writing a row for tenant B


async def _insert_for(db: Database, session_tenant: uuid.UUID, row_tenant: uuid.UUID) -> None:
    async with db.tenant_session(TenantContext(session_tenant)) as session:
        user_id = uuid.uuid4()
        await session.execute(
            INSERT,
            {
                "id": user_id,
                "tenant": row_tenant,
                "sub": str(user_id),
                "email": f"{user_id}@t.test",
            },
        )


async def test_actor_columns_come_from_app_user_id(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = tenant_pair
    creator, editor = uuid.uuid4(), uuid.uuid4()
    user_id = await add_user(app_db, a, actor=creator)
    async with app_db.tenant_session(TenantContext(a, editor)) as session:
        # Raw SQL that even tries to forge the audit columns.
        await session.execute(
            text(
                "UPDATE users SET display_name = 'edited', created_by = :forged, "
                "updated_by = :forged WHERE id = :id"
            ),
            {"id": user_id, "forged": uuid.uuid4()},
        )
        row = (
            await session.execute(
                text("SELECT created_by, updated_by FROM users WHERE id = :id"), {"id": user_id}
            )
        ).one()
    assert row.created_by == creator  # immutable after insert
    assert row.updated_by == editor  # always the acting user


async def test_app_cannot_delete_users(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = tenant_pair
    user_id = await add_user(app_db, a)
    with pytest.raises(ProgrammingError, match="permission denied"):
        async with app_db.tenant_session(TenantContext(a)) as session:
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
