"""Public, no-sign-in links: where a token is looked up, and the budgets that guard it.

Moved unchanged from the action-link routes (WP-030 s3, lane B's conditions) so another public
link (WP-046a S6: stopping mails to an address kept informed) has the same protections:

- the tenant comes from the address used (subdomain or verified domain), else the link's `?t=`
  slug; the address wins and a slug naming another tenant is refused;
- every way of not finding a tenant gives `NO_TENANT`, so the answer and its cost are a wrong
  token's (an unknown tenant must look like a wrong token);
- two rate-limit budgets per request, both keyed on the client address: one before any lookup,
  scoped to the address alone, and one after, scoped to the resolved tenant.

`PublicLinks(group, scope_name)` keeps each kind of link's budgets apart.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import valkey.exceptions
from fastapi import Request, Response

from app.core.database import Database
from app.core.errors import AppError, RateLimited
from app.shared.api.ratelimit import RATE_LIMITER_STATE, RateLimiter

# Where the address and the slug name no tenant, the token is looked up here: no tenant has this
# id, so row-level security finds nothing and the answer is the wrong token's, at its cost
# (lane B's review: an unknown tenant must look like a wrong token).
NO_TENANT = uuid.UUID(int=0)


def _address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# (database, host, base domain, slug) -> the tenant, or None: organization's `link_tenant`
# (shared code never imports a module, so the route hands it in).
TenantResolver = Callable[
    [Database, str | None, str | None, str | None], Awaitable[uuid.UUID | None]
]


@dataclass(frozen=True)
class PublicLinks:
    """One kind of public link: its rate-limit group and its address-only budget's name."""

    group: str  # e.g. "action_links_public"
    scope_name: str  # e.g. "action-links-address"
    resolver: TenantResolver

    async def tenant(
        self, request: Request, response: Response, database: Database, slug: str | None
    ) -> uuid.UUID:
        """Where the token is looked up: the address's tenant, else the link's `?t=` slug.

        The address (subdomain or verified domain) wins; a slug naming another tenant is
        refused. Without tenant subdomains (on-prem, k3s) the address names none and the slug
        does. It only decides where the token is looked up: the token is the secret, and a token
        used on another tenant's address is simply not found there. Every way of not finding a
        tenant gives `NO_TENANT`, so the answer and its cost are a wrong token's.
        """
        slug = slug or None  # an empty `?t=` is no slug (lane B)
        # Two limits (lane B's review). Before any lookup, both budgets keyed on the client
        # address alone: a sweep over slugs or tenants' addresses shares one budget, and no
        # client fills another's. After it, the resolved tenant's own budget, as before ?t=: junk
        # with unknown slugs only ever fills NO_TENANT's, which no real link uses. Every request
        # makes both hits.
        await self.limit(request, response, self.address_scope(request))
        tenant_id = await self.resolve(request, database, slug)
        # Enforces only: its headers would tell an unknown slug's shared count from a real one's.
        await self.limit(request, response, tenant_id, headers=False)
        return tenant_id

    async def resolve(self, request: Request, database: Database, slug: str | None) -> uuid.UUID:
        """The tenant the address or slug names; `NO_TENANT` when neither (or they differ)."""
        found = await self.resolver(
            database,
            request.headers.get("host"),
            request.app.state.settings.tenant_base_domain,
            slug,
        )
        return found if found is not None else NO_TENANT

    def address_scope(self, request: Request) -> uuid.UUID:
        """A budget scope of the client address alone, never shared with a tenant or client."""
        return uuid.uuid5(NO_TENANT, f"{self.scope_name}:{_address(request)}")

    async def limit(
        self, request: Request, response: Response, tenant_id: uuid.UUID, *, headers: bool = True
    ) -> None:
        """Rate limit by client address: there is no person to key on (lane B).

        `headers`: whether this hit's RateLimit-* headers go on the response.
        """
        limiter: RateLimiter | None = getattr(request.app.state, RATE_LIMITER_STATE, None)
        if limiter is None:
            return
        try:
            decision = await limiter.hit(self.group, tenant_id, f"address:{_address(request)}")
        except (valkey.exceptions.ValkeyError, OSError):
            return  # the limiter is down: the token stays the protection
        if not decision.allowed:
            raise RateLimited(
                params={"retry_after_seconds": decision.reset_seconds}, headers=decision.headers()
            )
        if headers:
            response.headers.update(decision.headers())


# Every answer of a public link route stays out of caches and sends no referrer, errors included
# (lane B's note on #490): a 404 or 429 answer is as public as a 200.
PRIVATE_HEADERS = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}


async def private_answers() -> AsyncIterator[None]:
    """A router dependency: an error a public link route raises carries PRIVATE_HEADERS too.

    Success answers set them on the response themselves; this covers the problem answers, which
    the error handler builds from the exception (its `headers`). List it first in the router's
    dependencies so it wraps the rate limits as well. FastAPI's own 422 for a malformed body is
    raised before any dependency and is not an AppError, so it goes without them; it holds
    nothing but the field errors (lane B, #501).
    """
    try:
        yield
    except AppError as exc:
        exc.headers.update(PRIVATE_HEADERS)
        raise
