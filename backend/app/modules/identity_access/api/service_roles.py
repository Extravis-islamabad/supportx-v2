"""A service identity's roles as the screens that own one show them (ADR-043 §6).

Shared by every module that owns service identities, so each says the same thing the same way:
a workflow's run-as identity today, a connector's next (the coordinator, 2026-11-11). The owning
module finds its identity, checks its own permission, and calls `service_roles_out`; roles are
given and taken only through `assign_service_identity_role` / `remove_service_identity_role`.
"""

import uuid

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.service.policy import PolicyService
from app.modules.identity_access.service.roles import ServiceRole, roles_for_service
from app.modules.identity_access.service.service_identities import service_identity


class ServiceRoleOut(BaseModel):
    """A role as a service identity's screen names it: system roles by key, others by name."""

    id: uuid.UUID
    key: str
    name: str
    system: bool


class ServiceRolesOut(BaseModel):
    """A service identity, the roles given to it, and the roles it may be given."""

    made: bool = Field(description="False while the identity does not exist yet.")
    name: str | None
    active: bool
    roles: list[ServiceRoleOut] = Field(description="The roles given to it; none by default.")
    offered: list[ServiceRoleOut] = Field(
        description="Roles a service identity may hold (the server's rule), for the picker."
    )


def _out(role: ServiceRole) -> ServiceRoleOut:
    return ServiceRoleOut(id=role.id, key=role.key, name=role.name, system=role.system)


async def service_roles_out(
    session: AsyncSession,
    policy: PolicyService,
    subject: Subject,
    identity_id: uuid.UUID | None,
) -> ServiceRolesOut:
    """The identity (None: not made yet), its roles, and the roles `subject` may give it."""
    offered = [_out(r) for r in await roles_for_service(session, policy, subject)]
    if identity_id is None:
        return ServiceRolesOut(made=False, name=None, active=False, roles=[], offered=offered)
    found = await service_identity(session, identity_id)
    return ServiceRolesOut(
        made=True,
        name=found.name,
        active=found.active,
        roles=[_out(r) for r in found.roles],
        offered=offered,
    )
