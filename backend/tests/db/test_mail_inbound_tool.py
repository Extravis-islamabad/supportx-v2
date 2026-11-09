"""`make mail-inbound-test` (QA6-NTF-01): one e-mail through the real inbound pipeline on dev."""

import argparse
from pathlib import Path

import pytest

from tests.db.test_mail_inbound import SETTINGS, World, world  # noqa: F401 - the fixture, reused
from tooling import mail_inbound

pytestmark = pytest.mark.db


def _args(world: World, *extra: str) -> argparse.Namespace:  # noqa: F811 - the fixture's name
    return mail_inbound.parse_args(
        ["--tenant", str(world.tenant), "--from", "sara@acme.test", *extra]
    )


async def test_one_mail_goes_through_the_inbound_pipeline_once(world: World) -> None:  # noqa: F811
    args = _args(world, "--mailbox", "it@acme.test", "--subject", "Projector is dead")
    first = await mail_inbound.run(world.db.migrator_url, SETTINGS, args)
    assert first.startswith("it@acme.test: ")
    assert [c["subject"] for c in world.incidents.created] == ["Projector is dead"]


async def test_the_same_eml_twice_is_skipped_the_second_time(
    world: World,  # noqa: F811
    tmp_path: Path,
) -> None:
    args = _args(world, "--mailbox", "it@acme.test")
    path = Path(str(tmp_path)) / "message.eml"
    path.write_bytes(mail_inbound.build(args, "it@acme.test"))
    again = _args(world, "--mailbox", "it@acme.test", "--eml", str(path))
    await mail_inbound.run(world.db.migrator_url, SETTINGS, again)
    second = await mail_inbound.run(world.db.migrator_url, SETTINGS, again)
    assert second.endswith("seen before (same Message-ID), skipped")
    assert len(world.incidents.created) == 1


async def test_without_a_mailbox_it_says_how_to_get_one(world: World) -> None:  # noqa: F811
    args = _args(world, "--mailbox", "nobody@acme.test")
    with pytest.raises(SystemExit, match="pass --create"):
        await mail_inbound.run(world.db.migrator_url, SETTINGS, args)
