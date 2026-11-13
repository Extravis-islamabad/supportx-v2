"""Copied invite links, the admin side (REQ-SEC-021; WP-057 S2b-2; lane B's conditions 1 and 5).

With no outgoing mail: an invitation is delivered by a link (the Keycloak account made, no
e-mail). Copying it gives a 32-byte token once, in the link's fragment, keeping only its SHA-256;
a second copy replaces the first; revoking, stopping sign-in or deactivating clears it. With mail
set up there is no link to copy. Each copy is audited, never with the token.
"""

import hashlib
import json
import logging
from urllib.parse import urlsplit

import pytest

from tests.db.test_identity_api import World, _admin_rows, _invite, _person, _slug, world

__all__ = ["world"]  # the fixture, re-used


def _no_mail(world: World) -> None:
    world.app.state.settings = world.app.state.settings.model_copy(
        update={"mail_smtp_host": None, "mail_from_address": None}
    )


async def _copy(world: World, invitation_id: str, version: int) -> tuple[int, dict[str, object]]:
    copied = await world.call(
        "POST",
        f"/identity/invitations/{invitation_id}/link",
        world.a,
        headers={"If-Match": f'"{version}"'},
    )
    return copied.status_code, (copied.json() if copied.content else {})


async def _stored_hash(world: World, invitation_id: str) -> bytes | None:
    (row,) = await _admin_rows(
        world.db, "SELECT link_token_hash FROM invitations WHERE id = $1::uuid", invitation_id
    )
    found = row["link_token_hash"]
    return None if found is None else bytes(found)


async def test_without_mail_a_link_is_copied_once_and_only_its_hash_is_kept(world: World) -> None:
    _no_mail(world)
    emails_before = len(world.admin.emails)
    invitation = await _invite(world, await _person(world, "link@acme.test"))
    assert invitation["delivery"] == "link"
    assert len(world.admin.emails) == emails_before  # no e-mail asked of Keycloak
    assert world.admin.verified["link@acme.test"] is False  # no mailbox reached: not proven
    status, first = await _copy(world, str(invitation["id"]), int(str(invitation["version"])))
    assert status == 200, first
    link = urlsplit(str(first["link"]))
    assert link.path.endswith("/invite")
    assert "token" not in link.query  # the token is only ever in the fragment
    token = link.fragment.removeprefix("token=")
    assert len(token) >= 43
    stored = await _stored_hash(world, str(invitation["id"]))
    assert stored == hashlib.sha256(token.encode()).digest()
    # A second copy replaces it: the first link stops working.
    status, second = await _copy(world, str(invitation["id"]), int(str(invitation["version"])) + 1)
    assert status == 200, second
    again = urlsplit(str(second["link"])).fragment.removeprefix("token=")
    assert again != token
    assert (
        await _stored_hash(world, str(invitation["id"])) == hashlib.sha256(again.encode()).digest()
    )
    # Audited with the admin, never the token.
    entries = await _admin_rows(
        world.db,
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        world.a.tenant,
        "invitation.link_copied",
    )
    assert len(entries) == 2
    assert all(token not in json.dumps(e["details"]) for e in entries)


async def test_revoking_clears_the_link(world: World) -> None:
    _no_mail(world)
    invitation = await _invite(world, await _person(world, "gone@acme.test"))
    version = int(str(invitation["version"]))
    status, _ = await _copy(world, str(invitation["id"]), version)
    assert status == 200
    revoked = await world.call(
        "POST",
        f"/identity/invitations/{invitation['id']}/revoke",
        world.a,
        headers={"If-Match": f'"{version + 1}"'},
    )
    assert revoked.status_code == 200, revoked.text
    assert await _stored_hash(world, str(invitation["id"])) is None


async def test_with_mail_set_up_there_is_no_link_to_copy(world: World) -> None:
    invitation = await _invite(world, await _person(world, "mailed@acme.test"))
    assert invitation["delivery"] == "email"
    status, body = await _copy(world, str(invitation["id"]), int(str(invitation["version"])))
    assert (status, body.get("code")) == (409, "invite_link_mail_configured")


# --- The person's side: the public routes (lane B's public-side conditions) ----------------------

PUBLIC = "/api/v1/public/invite-links"
GOOD = "Fresh-Start-42!x"  # meets the fake Keycloak's policy (12 characters at least)


async def _copied(world: World, email: str) -> tuple[str, str, str]:
    """(invitation ID, token, tenant slug) of a link copied for a newly invited person."""
    _no_mail(world)
    invitation = await _invite(world, await _person(world, email))
    status, body = await _copy(world, str(invitation["id"]), int(str(invitation["version"])))
    assert status == 200, body
    link = urlsplit(str(body["link"]))
    slug = dict(p.split("=", 1) for p in link.query.split("&") if p)["t"]
    return str(invitation["id"]), link.fragment.removeprefix("token="), slug


async def test_a_copied_link_sets_the_first_password_once(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    invitation, token, slug = await _copied(world, "fresh@acme.test")
    peeked = await world.client.post(f"{PUBLIC}/peek", json={"token": token, "tenant": slug})
    assert peeked.status_code == 200, peeked.text
    assert peeked.json()["app"] == "portal"
    assert peeked.json()["rules"]["min_length"] >= 8
    assert peeked.headers["cache-control"] == "no-store"
    assert peeked.headers["referrer-policy"] == "no-referrer"
    # A policy error only now that the token checked out, and labelled.
    weak = await world.client.post(
        f"{PUBLIC}/accept", json={"token": token, "tenant": slug, "password": "short"}
    )
    assert weak.status_code == 422, weak.text
    assert weak.json()["errors"][0]["code"] == "password_too_short"
    done = await world.client.post(
        f"{PUBLIC}/accept", json={"token": token, "tenant": slug, "password": GOOD}
    )
    assert done.status_code == 204, done.text
    (row,) = await _admin_rows(
        world.db,
        "SELECT status, link_token_hash, keycloak_user_id, user_id FROM invitations"
        " WHERE id = $1::uuid",
        invitation,
    )
    assert (row["status"], row["link_token_hash"]) == ("accepted", None)
    account = row["keycloak_user_id"]
    assert world.admin.passwords_set == [account]
    assert "UPDATE_PASSWORD" not in world.admin.required.get(account, [])
    (entry,) = await _admin_rows(
        world.db,
        "SELECT actor_type, actor_id FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'invitation.accepted'",
        world.a.tenant,
    )
    assert (entry["actor_type"], entry["actor_id"]) == ("person", row["user_id"])
    # Once: the same link again is the one answer for every link that does not work.
    again = await world.client.post(
        f"{PUBLIC}/accept", json={"token": token, "tenant": slug, "password": GOOD}
    )
    assert (again.status_code, again.json()["code"]) == (404, "invite_link_invalid")
    # Neither the token nor the password is ever logged.
    assert token not in caplog.text
    assert GOOD not in caplog.text


async def test_every_link_that_does_not_work_gets_one_answer(world: World) -> None:
    _invitation, token, slug = await _copied(world, "nope@acme.test")
    other = await _slug(world.db, world.b.tenant)
    for body in (
        {"token": "x" * 43, "tenant": slug},  # wrong token
        {"token": "short", "tenant": slug},  # not a token's shape
        {"token": token, "tenant": other},  # another tenant
        {"token": token, "tenant": "no-such-tenant"},  # no tenant
        {"token": token},  # no tenant named by the address either
    ):
        found = await world.client.post(f"{PUBLIC}/peek", json=body)
        assert (found.status_code, found.json()["code"]) == (404, "invite_link_invalid"), body
        tried = await world.client.post(f"{PUBLIC}/accept", json={**body, "password": "short"})
        # Never a policy error before the token checked out (lane B).
        assert (tried.status_code, tried.json()["code"]) == (404, "invite_link_invalid"), body
    assert world.admin.passwords_set == []
