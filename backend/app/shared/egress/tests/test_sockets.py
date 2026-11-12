"""The address a tenant-typed host may be reached at (audit #3), without a network."""

import ipaddress

import pytest

from app.shared.egress.addresses import Allowance, IPAddress
from app.shared.egress.client import EgressError
from app.shared.egress.sockets import NOT_ALLOWED, UNRESOLVED, pinned_address

NONE = Allowance()


class FakeResolver:
    """Answers a fixed set of addresses and counts how often it was asked."""

    def __init__(self, *answers: str) -> None:
        self.answers = [ipaddress.ip_address(a) for a in answers]
        self.calls: list[str] = []

    async def __call__(self, host: str, port: int) -> list[IPAddress]:
        del port
        self.calls.append(host)
        return list(self.answers)


def resolver(*answers: str) -> FakeResolver:
    return FakeResolver(*answers)


@pytest.mark.parametrize(
    "answer",
    [
        "10.0.0.5",  # private
        "127.0.0.1",  # loopback
        "169.254.169.254",  # link-local: cloud metadata
        "100.64.0.1",  # CGNAT
        "::1",  # IPv6 loopback
        "::ffff:10.0.0.5",  # an IPv6 form carrying a private IPv4
        "fe80::1",  # IPv6 link-local
    ],
)
async def test_a_name_resolving_to_an_address_no_tenant_may_reach_is_refused(answer: str) -> None:
    with pytest.raises(EgressError) as refused:
        await pinned_address("mail.example.com", 993, NONE, resolver(answer))
    assert refused.value.code == NOT_ALLOWED
    assert answer not in str(refused.value)  # never which address or range


async def test_one_bad_answer_among_good_ones_refuses_the_name() -> None:
    """Picking a good answer from a mixed set would let a rebinding name through."""
    with pytest.raises(EgressError) as refused:
        await pinned_address("mail.example.com", 993, NONE, resolver("93.184.216.34", "10.1.2.3"))
    assert refused.value.code == NOT_ALLOWED


async def test_a_public_name_is_pinned_to_its_address_resolved_once() -> None:
    resolve = resolver("93.184.216.34")
    pinned = await pinned_address("mail.example.com", 993, NONE, resolve)
    assert pinned == ipaddress.ip_address("93.184.216.34")
    assert resolve.calls == ["mail.example.com"]  # asked once


async def test_an_address_typed_as_such_is_judged_without_resolving() -> None:
    resolve = resolver()
    with pytest.raises(EgressError):
        await pinned_address("192.168.1.10", 143, NONE, resolve)
    assert resolve.calls == []  # never resolved


async def test_a_name_that_does_not_resolve_is_unreachable() -> None:
    with pytest.raises(EgressError) as missing:
        await pinned_address("nowhere.example.com", 993, NONE, resolver())
    assert missing.value.code == UNRESOLVED


async def test_the_installation_may_open_its_own_private_range() -> None:
    """Only configuration opens a private network, never a tenant."""
    opened = Allowance.from_config(["10.20.0.0/16"])
    pinned = await pinned_address("mail.internal.example", 993, opened, resolver("10.20.1.4"))
    assert pinned == ipaddress.ip_address("10.20.1.4")
