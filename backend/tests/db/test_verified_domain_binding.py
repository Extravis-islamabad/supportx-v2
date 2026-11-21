"""A verified domain never widens #554's binding (WP-057 S5d; lane B's condition 3, its BFF half).

Keycloak routes an address in tenant A's verified domain to A's provider (the integration test
on #568's fixture covers that half). Here, the half SupportX decides: a brokered sign-in through
A's provider opens tenant A, and never tenant B, even for an address in A's verified domain.
"""

import uuid

from tests.db.test_auth_bff import Bff, bff
from tests.db.test_sso_required_sign_in import _provider, _sql

__all__ = ["bff"]  # the fixture, re-used

DOMAIN = "a-corp-verified.test"


async def _verified(bff: Bff, tenant: uuid.UUID) -> None:
    await _sql(
        bff.db,
        "INSERT INTO verified_domains (id, tenant_id, domain, state, token_digest, verified_at,"
        " verified_by_method, created_at, updated_at) VALUES (gen_random_uuid(), $1, $2,"
        " 'verified', $3, now(), 'dns', now(), now())",
        tenant,
        DOMAIN,
        b"\x00" * 32,
    )


async def test_a_verified_domain_never_opens_another_tenant(bff: Bff) -> None:
    a, b = bff.tenants
    await _verified(bff, a)
    await _provider(bff.db, a, "a-corp-idp")
    # A's own person, in A's verified domain, through A's provider: in.
    mine = bff.user(
        "a", email=f"ali-{uuid.uuid4().hex[:6]}@{DOMAIN}", identity_provider="a-corp-idp"
    )
    assert (await bff.login(mine)).status_code == 302
    # The same domain and provider landing on a person of tenant B: refused, nothing made.
    other = bff.user(
        "b", email=f"bina-{uuid.uuid4().hex[:6]}@{DOMAIN}", identity_provider="a-corp-idp"
    )
    refused = await bff.login(other)
    assert (refused.status_code, refused.json()["code"]) == (403, "sso_provider_not_this_tenant")
    made = await _sql(
        bff.db,
        "SELECT count(*) AS n FROM users WHERE tenant_id = $1 AND email = $2",
        b,
        other.email,
    )
    assert made[0]["n"] == 0
