"""Printing an incident (WP-046b S4, REQ-INC-126; lane B): the printout reads the APIs the
reader already uses, and "public notes only" is a server filter, so a private note never reaches
the printed page (AC1). Masked and sealed values come as those APIs already return them.
"""

from tests.db.test_incidents_api import BASE, CONSOLE, World, world  # noqa: F401 - fixture


async def test_public_only_leaves_private_notes_on_the_server(world: World) -> None:  # noqa: F811
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    notes = (("public", "Restarted the mail relay"), ("private", "Vendor PIN 4411"))
    for visibility, text in notes:
        added = await world.call(
            "POST",
            f"{BASE}/{item['id']}/conversation",
            a,
            a.admin,
            json={"kind": "note", "visibility": visibility, "body": f"<p>{text}</p>"},
            headers=CONSOLE,
        )
        assert added.status_code == 201, added.text
    printed = await world.call(
        "GET", f"{BASE}/{item['id']}/conversation?visibility=public", a, a.admin
    )
    assert printed.status_code == 200, printed.text
    assert "Restarted the mail relay" in printed.text
    assert "Vendor PIN 4411" not in printed.text
    everything = await world.call("GET", f"{BASE}/{item['id']}/conversation", a, a.admin)
    assert "Vendor PIN 4411" in everything.text  # staff still see both without the filter
