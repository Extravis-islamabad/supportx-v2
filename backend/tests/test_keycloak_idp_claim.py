"""The `sx_idp` claim mapper on the app clients (WP-057 S1b; lane B's condition 2).

The identity step adds it to realms made before it, puts it back when someone changed it (for
example turned userinfo on), and changes nothing when it is right: idempotent.
"""

import json
from typing import Any

import httpx

from tooling.keycloak_identity import APP_CLIENTS, IDP_CLAIM_MAPPER, _ensure_idp_claim

BASE = "/admin/realms/supportx/clients"


class Realm:
    """The two app clients and their mappers; every write recorded."""

    def __init__(self) -> None:
        self.mappers: dict[str, list[dict[str, Any]]] = {f"id-{c}": [] for c in APP_CLIENTS}
        self.writes: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if path == BASE:
            wanted = request.url.params["clientId"]
            return httpx.Response(200, json=[{"id": f"id-{wanted}", "clientId": wanted}])
        internal = path.removeprefix(f"{BASE}/").split("/")[0]
        found = self.mappers[internal]
        if method != "GET":
            self.writes.append(f"{method} {internal}")
        if method == "POST":
            found.append({**json.loads(request.content), "id": f"m-{internal}"})
            return httpx.Response(201)
        if method == "PUT":
            found[0] = json.loads(request.content)
            return httpx.Response(204)
        return httpx.Response(200, json=found)


async def _run(realm: Realm) -> list[str]:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(realm.handle), base_url="http://kc"
    ) as client:
        return await _ensure_idp_claim(client, {}, "supportx")


async def test_the_claim_is_added_once_and_never_on_userinfo() -> None:
    realm = Realm()
    assert len(await _run(realm)) == len(APP_CLIENTS)
    for mappers in realm.mappers.values():
        (mapper,) = mappers
        assert mapper["config"]["user.session.note"] == "identity_provider"
        assert mapper["config"]["claim.name"] == "sx_idp"
        assert mapper["config"]["userinfo.token.claim"] == "false"
    realm.writes.clear()
    assert await _run(realm) == []  # idempotent
    assert realm.writes == []


async def test_a_changed_mapper_is_put_back() -> None:
    realm = Realm()
    await _run(realm)
    drifted = realm.mappers["id-supportx-console"][0]
    drifted["config"] = {**drifted["config"], "userinfo.token.claim": "true"}
    assert await _run(realm) == ["supportx-console: sign-in identity provider claim set back"]
    assert realm.mappers["id-supportx-console"][0]["config"] == IDP_CLAIM_MAPPER["config"]
