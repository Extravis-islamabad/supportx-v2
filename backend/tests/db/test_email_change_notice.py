"""A changed sign-in e-mail is told to the OLD address (WP-057 S2b-1; the coordinator, #479).

Who changed it and when, in the person's language and the tenant's brand, with no link at all
(nothing that undoes the change silently). Not for any other field, nor for the same address
sent back. The change itself needs a recent confirmation (#479's test).
"""

from tests.db.test_identity_api import World, _admin_rows, _sql, world

__all__ = ["world"]  # the fixture, re-used


async def _change(world: World, user: object, change: dict[str, str]) -> int:
    current = await world.call("GET", f"/users/{user}", world.a)
    assert current.status_code == 200, current.text
    done = await world.call(
        "PATCH",
        f"/users/{user}/person",
        world.a,
        json=change,
        headers={"If-Match": current.headers["etag"]},
    )
    assert done.status_code == 200, done.text
    return done.status_code


async def _mail(world: World) -> list[tuple[str, list[str], str, str]]:
    rows = await _admin_rows(
        world.db,
        "SELECT kind, recipients, subject, text_body FROM mail_messages"
        " WHERE tenant_id = $1 AND kind = 'email_changed'",
        world.a.tenant,
    )
    return [(r["kind"], r["recipients"], r["subject"], r["text_body"] or "") for r in rows]


async def test_the_old_address_hears_who_changed_it_and_when(world: World) -> None:
    world.app.state.settings = world.app.state.settings.model_copy(
        update={"mail_smtp_host": "mail.test", "mail_from_address": "support@acme.test"}
    )
    await _sql(world, "UPDATE users SET email = 'old@acme.test' WHERE id = $1", world.a.tech)
    await _change(world, world.a.tech, {"job_title": "Field engineer"})  # not the e-mail
    await _change(world, world.a.tech, {"email": "old@acme.test"})  # the same one, sent back
    assert await _mail(world) == []
    await _change(world, world.a.tech, {"email": "new@acme.test"})
    ((kind, to, subject, text),) = await _mail(world)
    assert (kind, to) == ("email_changed", ["old@acme.test"])
    assert "sign-in e-mail" in subject
    admin = await _admin_rows(
        world.db, "SELECT display_name FROM users WHERE id = $1", world.a.admin
    )
    assert admin[0]["display_name"] in text  # who
    assert "new@acme.test" not in text  # never the new address
    assert "http" not in text  # no link, least of all one that undoes it
    (audited,) = await _admin_rows(
        world.db,
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = 'user.changed'"
        " AND details ? 'sign_in_email_changed'",
        world.a.tenant,
    )
    assert '"old_address_told": true' in audited["details"]  # the send, in the audit log
