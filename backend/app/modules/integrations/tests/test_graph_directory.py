"""The Graph directory client against a fake Graph (WP-040 session 2): paging, delta, refusals."""

from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx
import pytest

from app.modules.integrations.domain.directory import AttributeMapping
from app.modules.integrations.infra.graph_directory import (
    DELTA_EXPIRED,
    GRAPH_SCOPE,
    DeltaPage,
    DirectoryUnavailableError,
    GraphDirectory,
)
from app.modules.integrations.infra.oauth import OAUTH_NOT_ALLOWED, OAUTH_UNREACHABLE
from app.modules.integrations.tests.fake_directory import GRAPH, LOGIN, FakeDirectory, graph_id

SELECT = AttributeMapping().graph_select()


async def _client(fake: FakeDirectory) -> GraphDirectory:
    http = httpx.AsyncClient(transport=fake.transport())
    token = await http.post(
        f"{LOGIN}/tenant/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": fake.client_id,
            "client_secret": fake.client_secret,
            "scope": GRAPH_SCOPE,
        },
    )
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    client = GraphDirectory(http, GRAPH, token.json()["access_token"], sleep=sleep)
    client.waits = waits  # type: ignore[attr-defined]  # the test reads the throttling waits
    return client


async def _all(pages: AsyncIterator[DeltaPage]) -> tuple[list[Mapping[str, Any]], str | None]:
    items: list[Mapping[str, Any]] = []
    link = None
    async for page in pages:
        items += page.items
        link = page.delta_link
    return items, link


async def test_a_first_round_pages_through_everyone_then_only_changes_come() -> None:
    fake = FakeDirectory(page_size=2)
    ids = [fake.add_user(displayName=f"P{n}", mail=f"p{n}@alpha.test") for n in range(5)]
    client = await _client(fake)
    items, link = await _all(client.users(None, SELECT))
    assert sorted(i["id"] for i in items) == sorted(ids)
    assert link is not None
    assert fake.requests[-1].headers["Prefer"].endswith("odata.maxpagesize=999")
    fake.change_user(ids[1], jobTitle="Lead")
    fake.delete_user(ids[2])
    changed, next_link = await _all(client.users(link, SELECT))
    assert {i["id"]: i.get("@removed") for i in changed} == {
        ids[1]: None,
        ids[2]: {"reason": "deleted"},
    }
    assert next_link is not None
    assert await _all(client.users(next_link, SELECT)) == ([], next_link)
    await client.close()


async def test_throttling_waits_as_graph_asks_then_gives_up() -> None:
    fake = FakeDirectory()
    fake.add_user(mail="a@alpha.test")
    client = await _client(fake)
    fake.throttle_next = 2
    items, _ = await _all(client.users(None, SELECT))
    assert len(items) == 1
    assert client.waits == [1.0, 1.0]  # type: ignore[attr-defined]
    fake.throttle_next = 10
    with pytest.raises(DirectoryUnavailableError) as refused:
        await _all(client.users(None, SELECT))
    assert refused.value.code == OAUTH_UNREACHABLE
    await client.close()


async def test_an_expired_link_and_a_missing_permission_are_reported_by_code() -> None:
    fake = FakeDirectory()
    fake.add_user(mail="a@alpha.test")
    client = await _client(fake)
    _, link = await _all(client.users(None, SELECT))
    assert link is not None
    fake.expire_links = True
    with pytest.raises(DirectoryUnavailableError) as expired:
        await _all(client.users(link, SELECT))
    assert expired.value.code == DELTA_EXPIRED
    assert not expired.value.auth_failure
    fake.forbidden = True
    with pytest.raises(DirectoryUnavailableError) as forbidden:
        await _all(client.users(None, SELECT))
    assert forbidden.value.code == OAUTH_NOT_ALLOWED
    assert forbidden.value.auth_failure  # failing at once (D-118 defaults)
    await client.close()


async def test_the_token_is_never_sent_outside_graph() -> None:
    fake = FakeDirectory()
    client = await _client(fake)
    with pytest.raises(DirectoryUnavailableError):
        await _all(client.users("https://elsewhere.test/v1.0/users/delta?since=1", SELECT))
    assert not any(r.url.host == "elsewhere.test" for r in fake.requests)
    await client.close()


async def test_group_members_come_by_delta_and_only_real_ids_reach_the_filter() -> None:
    fake = FakeDirectory()
    ada, bob = fake.add_user(mail="ada@alpha.test"), fake.add_user(mail="bob@alpha.test")
    finance = fake.add_group("Finance", [ada, bob])
    fake.add_group("Other", [bob])
    client = await _client(fake)
    items, link = await _all(client.groups(None, [finance, "x') or true or ('"]))
    assert [i["id"] for i in items] == [finance]
    assert {m["id"] for m in items[0]["members@delta"]} == {ada, bob}
    assert "or true" not in str(fake.requests[-1].url)
    fake.set_members(finance, [ada])
    changed, _ = await _all(client.groups(link, [finance]))
    removed = [m["id"] for m in changed[0]["members@delta"] if "@removed" in m]
    assert removed == [bob]
    assert await client.group_names("fin") == [(finance, "Finance")]
    assert await client.group_names(graph_id()) == []
    await client.close()
