"""An OIDC client secret's expiry date on the SSO set-up (REQ-SEC-011; WP-057 S2b-2).

Saved with the set-up, shown again, and changed or cleared by the next save; SupportX never
reads the secret itself. The daily expiry alerts read it (tests/db/test_expiry_alerts.py).
"""

from datetime import UTC, datetime

from tests.db.test_identity_api import World, world

__all__ = ["world"]  # the fixture, re-used

WHEN = datetime(2027, 3, 31, 12, 0, tzinfo=UTC)


async def test_the_client_secret_expiry_is_saved_shown_and_cleared(world: World) -> None:
    made = await world.add_oidc(world.a, client_secret_expires_at=WHEN.isoformat())
    assert made.status_code == 201, made.text
    body = made.json()
    assert datetime.fromisoformat(body["client_secret_expires_at"]) == WHEN
    listed = (await world.call("GET", "/identity/sso", world.a)).json()["items"]
    (shown,) = [p for p in listed if p["id"] == body["id"]]
    assert datetime.fromisoformat(shown["client_secret_expires_at"]) == WHEN
    saved = await world.call(
        "PUT",
        f"/identity/sso/{body['id']}",
        world.a,
        json={
            "preset": "entra",
            "display_name": "Acme Entra ID",
            "domains": ["acme.test"],
            "issuer": body["settings"].get("issuer"),
            "client_id": "supportx",
            "client_secret_expires_at": None,
        },
        headers={"If-Match": f'"{body["version"]}"'},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["client_secret_expires_at"] is None
