"""Channel names, tokens, live-list audiences and the registry (WP-011), without I/O."""

import base64
import hashlib
import hmac
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.shared.realtime import (
    Channel,
    ChannelAccess,
    ChannelNameError,
    ChannelRequest,
    ChannelSpec,
    LiveList,
    RealtimeRegistrationError,
    RealtimeRegistry,
    RealtimeRoute,
    broadcast,
    connection_token,
    personal,
    queue,
    record,
    subscription_token,
)
from app.shared.realtime.tokens import AUDIENCE, ISSUER, decode_unverified, sign

TENANT = uuid.UUID("01900000-0000-7000-8000-0000000000a1")
OTHER = uuid.UUID("01900000-0000-7000-8000-0000000000b2")
USER = uuid.UUID("01900000-0000-7000-8000-000000000001")
SITE = uuid.UUID("01900000-0000-7000-8000-0000000000c1")
GROUP = uuid.UUID("01900000-0000-7000-8000-0000000000d1")


# --- channel names --------------------------------------------------------------------------------


def test_channel_names_follow_the_spec() -> None:
    assert record(TENANT, "wi", USER).name == f"t:{TENANT}:wi:{USER}"
    assert personal(TENANT, USER).name == f"t:{TENANT}:user:{USER}"
    assert broadcast(TENANT).name == f"t:{TENANT}:broadcast"
    assert queue(TENANT, "users").name == f"t:{TENANT}:queue:users"
    assert queue(TENANT, "users", site=SITE).name == f"t:{TENANT}:queue:users.site.{SITE}"
    assert queue(TENANT, "users", group=GROUP).list_name == "users"


def test_parse_round_trips() -> None:
    for channel in (record(TENANT, "users", USER), broadcast(TENANT), queue(TENANT, "roles")):
        assert Channel.parse(channel.name) == channel


@pytest.mark.parametrize(
    "name",
    [
        "",
        "x:1:users",
        f"t:{TENANT}",
        "t:not-a-uuid:users:1",
        f"t:{str(TENANT).upper()}:users:1",  # one channel, one spelling
        f"t:{TENANT}:Users:1",
        f"t:{TENANT}:users:a:b",
        f"t:{TENANT}:users:has space",
        f"t:{TENANT}:users:#private",
    ],
)
def test_parse_rejects_anything_else(name: str) -> None:
    with pytest.raises(ChannelNameError):
        Channel.parse(name)


# --- tokens ---------------------------------------------------------------------------------------


def _verify(token: str, secret: str) -> bool:
    header, payload, signature = token.split(".")
    expected = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    padded = signature + "=" * (-len(signature) % 4)
    return hmac.compare_digest(expected, base64.urlsafe_b64decode(padded))


def test_connection_token_carries_only_what_centrifugo_needs() -> None:
    token = connection_token(
        tenant_id=TENANT,
        user_id=USER,
        display_name="Aisha",
        secret="s" * 32,
        ttl_seconds=900,
        now=1000,
    )
    assert _verify(token, "s" * 32)
    assert not _verify(token, "t" * 32)
    assert decode_unverified(token) == {
        "sub": f"{TENANT}:{USER}",
        "aud": AUDIENCE,
        "iss": ISSUER,
        "iat": 1000,
        "exp": 1900,
        "info": {"user_id": str(USER), "name": "Aisha"},
    }


def test_subscription_token_names_one_channel_and_enables_presence_on_request() -> None:
    channel = record(TENANT, "users", USER).name
    plain = decode_unverified(
        subscription_token(
            tenant_id=TENANT, user_id=USER, channel=channel, secret="k", ttl_seconds=60, now=10
        )
    )
    assert plain["channel"] == channel
    assert plain["exp"] == 70
    assert "override" not in plain
    with_presence = decode_unverified(
        subscription_token(
            tenant_id=TENANT,
            user_id=USER,
            channel=channel,
            secret="k",
            ttl_seconds=60,
            presence=True,
        )
    )
    assert with_presence["override"]["presence"] == {"value": True}
    assert with_presence["override"]["join_leave"] == {"value": True}


def test_sign_is_standard_hs256() -> None:
    token = sign({"sub": "x"}, "secret")
    assert decode_unverified(token) == {"sub": "x"}
    assert token.count(".") == 2


# --- live lists -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class G:
    scope: str
    condition: Any = None


@dataclass(frozen=True)
class FakeSubject:
    tenant_id: uuid.UUID = TENANT
    user_id: uuid.UUID = USER
    site_ids: frozenset[uuid.UUID] = frozenset({SITE})
    group_ids: frozenset[uuid.UUID] = frozenset({GROUP})
    grants: dict[str, tuple[G, ...]] = field(default_factory=dict)


USERS = LiveList("users", "users.view")


def names(channels: list[Channel]) -> list[str]:
    return [c.name for c in channels]


def test_all_scope_follows_the_one_list_channel() -> None:
    subject = FakeSubject(grants={"users.view": (G("all"), G("own"))})
    assert names(USERS.channels_for(subject, TENANT)) == [queue(TENANT, "users").name]


def test_narrow_scopes_follow_their_audiences_only() -> None:
    subject = FakeSubject(grants={"users.view": (G("site"), G("group"), G("own"))})
    assert names(USERS.channels_for(subject, TENANT)) == [
        queue(TENANT, "users", site=SITE).name,
        queue(TENANT, "users", group=GROUP).name,
        personal(TENANT, USER).name,
    ]


def test_rule_bound_grants_get_the_id_free_signal_channel() -> None:
    subject = FakeSubject(
        grants={"users.view": (G("all", {"field": "x", "op": "eq", "value": 1}),)}
    )
    assert names(USERS.channels_for(subject, TENANT)) == [f"t:{TENANT}:queue:users.signal"]


def test_no_grant_no_channel() -> None:
    assert USERS.channels_for(FakeSubject(), TENANT) == []


async def test_authorize_matches_channels_for() -> None:
    subject = FakeSubject(grants={"users.view": (G("site"),)})

    async def ask(channel: Channel) -> ChannelAccess | None:
        request = ChannelRequest(channel, TENANT, USER, subject, session=None)  # type: ignore[arg-type]  # unused by LiveList
        return await USERS.authorize(request)

    assert await ask(queue(TENANT, "users", site=SITE)) == ChannelAccess()
    assert await ask(queue(TENANT, "users")) is None  # the everyone channel needs `all`
    assert await ask(queue(TENANT, "users", site=uuid.uuid4())) is None  # not their site
    assert await ask(queue(TENANT, "users", group=GROUP)) is None  # no group grant


def test_publications_reach_every_audience_and_the_signal_without_ids() -> None:
    pubs = USERS.publications(
        TENANT, "users.changed", USER, sites=[SITE], groups=[GROUP], owners=[USER], actor_id="a"
    )
    by_channel = {p.channel.name: p for p in pubs}
    assert set(by_channel) == {
        queue(TENANT, "users").name,
        queue(TENANT, "users", site=SITE).name,
        queue(TENANT, "users", group=GROUP).name,
        personal(TENANT, USER).name,
        f"t:{TENANT}:queue:users.signal",
    }
    assert all(p.coalesce for p in pubs)
    assert by_channel[f"t:{TENANT}:queue:users.signal"].data() == {
        "type": "users.changed",
        "ids": [],
    }
    assert by_channel[queue(TENANT, "users").name].data() == {
        "type": "users.changed",
        "ids": [str(USER)],
        "by": "a",
    }


# --- registry -------------------------------------------------------------------------------------


@dataclass
class FakeModule:
    name: str
    channels: list[object] = field(default_factory=list)
    realtime: list[object] = field(default_factory=list)


async def _deny(_request: ChannelRequest) -> ChannelAccess | None:
    return None


def test_registry_collects_specs_and_routes() -> None:
    async def route(*_: object) -> Any:  # noqa: ANN401 - not called
        raise AssertionError

    registry = RealtimeRegistry.build(
        [
            FakeModule(
                "a",
                channels=[ChannelSpec("users", _deny), USERS.spec()],
                realtime=[RealtimeRoute(("a.b.c",), route)],
            )
        ]
    )
    assert registry.spec_for(record(TENANT, "users", USER)) is not None
    assert registry.spec_for(queue(TENANT, "users", site=SITE)) is not None
    assert registry.spec_for(queue(TENANT, "roles")) is None
    assert registry.spec_for(record(OTHER, "wi", USER)) is None
    assert registry.lists() == ["users"]
    assert registry.event_types() == ["a.b.c"]


@pytest.mark.parametrize(
    "module",
    [
        FakeModule("a", channels=["not a spec"]),
        FakeModule("a", channels=[ChannelSpec("users", _deny), ChannelSpec("users", _deny)]),
        FakeModule("a", channels=[ChannelSpec("queue", _deny, list_name="x")]),  # no channels_for
        FakeModule("a", realtime=[RealtimeRoute((), _deny)]),  # type: ignore[arg-type]  # deliberately wrong
    ],
)
def test_registry_rejects_bad_declarations(module: FakeModule) -> None:
    with pytest.raises(RealtimeRegistrationError):
        RealtimeRegistry.build([module])
