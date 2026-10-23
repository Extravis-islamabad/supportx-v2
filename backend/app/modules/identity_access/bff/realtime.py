"""Realtime tokens under /api/v1/realtime (architecture.md §8.2; WP-011).

The browser never gets a long-lived credential: it asks for a connection token (signed-in users
only, about 15 minutes) and, per channel, a subscription token that is only signed after the
policy layer allowed that channel (about 5 minutes). centrifuge-js asks again before they expire,
so a lost permission stops the next renewal at the latest; revocation cuts it at once.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.authorization import require_signed_in
from app.core.config import Settings
from app.core.database import TenantSession
from app.core.entitlements import read_only_exempt
from app.core.errors import NotFound, PermissionDenied, ServiceUnavailable, Unauthenticated
from app.core.tenancy import resolve_tenant
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.infra.models import User
from app.shared.realtime import (
    REALTIME_STATE,
    Channel,
    ChannelNameError,
    ChannelRequest,
    RealtimeRegistry,
    connection_token,
    subscription_token,
)

router = APIRouter(prefix="/realtime", tags=["realtime"])

_signed_in = require_signed_in()


async def signed_in_user(
    request: Request, subject: Annotated[Subject, Depends(_signed_in)]
) -> Subject:
    """A signed-in subject that is a user: a token names a person, never a tenant alone.

    (The dev-only tenant header can produce a context without a user; it gets 401 here.)
    """
    if (await resolve_tenant(request)).user_id is None:
        raise Unauthenticated
    return subject


SignedIn = Annotated[Subject, Depends(signed_in_user)]


class RealtimeToken(BaseModel):
    """A short-lived Centrifugo token."""

    token: str
    expires_in: int = Field(description="Seconds until the token expires.")


class SubscriptionTokenRequest(BaseModel):
    """The channel to join, e.g. `t:<tenant>:users:<user id>`."""

    channel: str = Field(max_length=256)


class LiveListChannels(BaseModel):
    """The channels to join to follow one list live (one per audience the user belongs to)."""

    channels: list[str]


def _secret(request: Request) -> tuple[Settings, str]:
    settings: Settings = request.app.state.settings
    if settings.centrifugo_token_secret is None:
        raise ServiceUnavailable(code="realtime_not_configured")
    return settings, settings.centrifugo_token_secret.get_secret_value()


def _registry(request: Request) -> RealtimeRegistry:
    registry: RealtimeRegistry = getattr(request.app.state, REALTIME_STATE)
    return registry


@router.post("/connection-token", summary="Realtime connection token")
@read_only_exempt
async def get_connection_token(
    subject: SignedIn, db: TenantSession, request: Request
) -> RealtimeToken:
    """Lets the signed-in user connect to the realtime gateway for the session's tenant.

    Signed in means a valid BFF session (CSRF-checked: this is a POST), resolved for the tenant.
    """
    settings, secret = _secret(request)
    name = await db.scalar(select(User.display_name).where(User.id == subject.user_id))
    ttl = settings.realtime_connection_token_ttl_seconds
    token = connection_token(
        tenant_id=subject.tenant_id,
        user_id=subject.user_id,
        display_name=name or "",
        secret=secret,
        ttl_seconds=ttl,
    )
    return RealtimeToken(token=token, expires_in=ttl)


@router.post(
    "/subscription-token",
    summary="Realtime subscription token",
    responses={403: {"description": "Not allowed to join this channel (realtime_channel_denied)."}},
)
@read_only_exempt
async def get_subscription_token(
    body: SubscriptionTokenRequest,
    subject: SignedIn,
    db: TenantSession,
    request: Request,
) -> RealtimeToken:
    """Signed only when the policy layer allows this user to see what the channel carries.

    Refused (403 `realtime_channel_denied`) for another tenant's channel, an unknown kind, or a
    record or list the user may not see.
    """
    settings, secret = _secret(request)
    try:
        channel = Channel.parse(body.channel)
    except ChannelNameError as exc:
        raise PermissionDenied(code="realtime_channel_denied") from exc
    spec = _registry(request).spec_for(channel)
    if channel.tenant_id != subject.tenant_id or spec is None:
        raise PermissionDenied(code="realtime_channel_denied")
    access = await spec.authorize(
        ChannelRequest(
            channel=channel,
            tenant_id=subject.tenant_id,
            user_id=subject.user_id,
            subject=subject,
            session=db,
        )
    )
    if access is None:
        raise PermissionDenied(code="realtime_channel_denied")
    ttl = settings.realtime_subscription_token_ttl_seconds
    token = subscription_token(
        tenant_id=subject.tenant_id,
        user_id=subject.user_id,
        channel=channel.name,
        secret=secret,
        ttl_seconds=ttl,
        presence=access.presence,
    )
    return RealtimeToken(token=token, expires_in=ttl)


@router.get("/lists/{name}", summary="Channels of a live list")
async def list_channels(name: str, subject: SignedIn, request: Request) -> LiveListChannels:
    """Which channels to join to follow list `name` (`users`, `roles`…); empty without access."""
    registry = _registry(request)
    spec = registry.channels.get(("queue", name))
    if spec is None or spec.channels_for is None:
        raise NotFound
    channels = spec.channels_for(subject, subject.tenant_id)
    return LiveListChannels(channels=[c.name for c in channels])
