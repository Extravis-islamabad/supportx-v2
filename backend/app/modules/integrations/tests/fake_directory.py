"""A fake Microsoft Graph directory for sync tests (WP-040 session 2): no network, no account.

Keeps users and groups, and answers `/users/delta` and `/groups/delta` the way Graph does: the
first round pages through everyone, later rounds started from the delta link carry only what
changed since (`@removed` for people deleted, `members@delta` for membership). Tokens come from
the client-credentials grant of one known app.
"""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

LOGIN = "https://login.test"
GRAPH = "https://graph.test/v1.0"


def graph_id() -> str:
    """A new Graph object ID (a GUID)."""
    return str(uuid.uuid4())


@dataclass
class FakeDirectory:
    """The fake's state; tests change it between rounds and read `requests`."""

    client_id: str = "sync-app"
    client_secret: str = "sync-s3cret"
    page_size: int = 2
    users: dict[str, dict[str, Any]] = field(default_factory=dict)  # Any: Graph JSON
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)  # id -> {name, members}
    throttle_next: int = 0  # answer this many calls with 429 first
    expire_links: bool = False  # every delta link answers 410
    forbidden: bool = False  # the app lacks the permission (403)
    requests: list[httpx.Request] = field(default_factory=list)
    _tick: itertools.count[int] = field(default_factory=itertools.count)
    # Change log: (tick, kind, id); a delta link remembers the tick it was issued at.
    _changes: list[tuple[int, str, str]] = field(default_factory=list)
    _tokens: set[str] = field(default_factory=set)

    def transport(self) -> httpx.MockTransport:
        """The httpx transport to install."""
        return httpx.MockTransport(self._handle)

    # --- changing the directory -----------------------------------------------------------------

    def add_user(self, **attributes: Any) -> str:  # noqa: ANN401 - Graph attributes
        """Add a user (Graph attribute names); returns its ID."""
        user_id = attributes.pop("id", None) or graph_id()
        self.users[user_id] = {"id": user_id, "accountEnabled": True, **attributes}
        self._changes.append((next(self._tick), "user", user_id))
        return user_id

    def change_user(self, user_id: str, **attributes: Any) -> None:  # noqa: ANN401
        """Change some of a user's attributes."""
        self.users[user_id].update(attributes)
        self._changes.append((next(self._tick), "user", user_id))

    def delete_user(self, user_id: str) -> None:
        """Delete a user (they appear as `@removed`)."""
        self.users[user_id]["@deleted"] = True
        self._changes.append((next(self._tick), "user", user_id))

    def add_group(self, name: str, members: list[str]) -> str:
        """Add a group with members; returns its ID."""
        group_id = graph_id()
        self.groups[group_id] = {"name": name, "members": set(members), "removed": set()}
        self._changes.append((next(self._tick), "group", group_id))
        return group_id

    def set_members(self, group_id: str, members: list[str]) -> None:
        """Replace a group's members."""
        group = self.groups[group_id]
        group["removed"] = group["members"] - set(members)
        group["members"] = set(members)
        self._changes.append((next(self._tick), "group", group_id))

    # --- Graph ----------------------------------------------------------------------------------

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        ok = (
            form.get("grant_type") == "client_credentials"
            and form.get("client_id") == self.client_id
            and form.get("client_secret") == self.client_secret
            and form.get("scope") == "https://graph.microsoft.com/.default"
        )
        if not ok:
            return httpx.Response(401, json={"error": "invalid_client"})
        token = f"tok-{uuid.uuid4().hex}"
        self._tokens.add(token)
        return httpx.Response(
            200, json={"access_token": token, "token_type": "Bearer", "expires_in": 3600}
        )

    def _user_item(self, user_id: str, select: list[str]) -> dict[str, Any]:
        user = self.users[user_id]
        if user.get("@deleted"):
            return {"id": user_id, "@removed": {"reason": "deleted"}}
        return {k: v for k, v in user.items() if k == "id" or k in select}

    def _group_item(self, group_id: str, since: int) -> dict[str, Any]:
        group = self.groups[group_id]
        # Simpler than Graph (which sends only the changed members later): every current member,
        # plus the removed ones after the first round. Applying a member twice changes nothing.
        members = [
            {"@odata.type": "#microsoft.graph.user", "id": m} for m in sorted(group["members"])
        ]
        if since >= 0:
            members += [
                {"id": m, "@removed": {"reason": "deleted"}} for m in sorted(group["removed"])
            ]
        return {"id": group_id, "displayName": group["name"], "members@delta": members}

    def _page(self, kind: str, query: dict[str, str]) -> httpx.Response:
        since = int(query.get("since", "-1"))
        if since >= 0 and self.expire_links:
            return httpx.Response(410, json={"error": {"code": "resyncRequired"}})
        select = query.get("$select", "").split(",")
        if kind == "user":
            ids = sorted(
                self.users
                if since < 0
                else {i for t, k, i in self._changes if k == "user" and t > since}
            )
            if since < 0:
                ids = [i for i in ids if not self.users[i].get("@deleted")]
        else:
            wanted = query.get("$filter", "")
            ids = sorted(
                g
                for g in self.groups
                if f"'{g}'" in wanted
                and (
                    since < 0
                    or any(k == "group" and i == g and t > since for t, k, i in self._changes)
                )
            )
        start = int(query.get("skip", "0"))
        chunk = ids[start : start + self.page_size]
        items = [
            self._user_item(i, select) if kind == "user" else self._group_item(i, since)
            for i in chunk
        ]
        path = "users" if kind == "user" else "groups"
        base = {k: v for k, v in query.items() if k != "skip"}
        if start + self.page_size < len(ids):
            link = httpx.URL(
                f"{GRAPH}/{path}/delta", params={**base, "skip": str(start + self.page_size)}
            )
            return httpx.Response(200, json={"value": items, "@odata.nextLink": str(link)})
        now = self._changes[-1][0] if self._changes else -1
        link = httpx.URL(f"{GRAPH}/{path}/delta", params={**base, "since": str(now)})
        return httpx.Response(200, json={"value": items, "@odata.deltaLink": str(link)})

    def _handle(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911 - one answer per Graph call
        self.requests.append(request)
        url = urlsplit(str(request.url))
        if str(request.url).startswith(f"{LOGIN}/") and url.path.endswith("/token"):
            return self._token(request)
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token not in self._tokens:
            return httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken"}})
        if self.throttle_next:
            self.throttle_next -= 1
            return httpx.Response(429, headers={"Retry-After": "1"})
        if self.forbidden:
            return httpx.Response(403, json={"error": {"code": "Authorization_RequestDenied"}})
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path.endswith("/users/delta"):
            return self._page("user", query)
        if url.path.endswith("/groups/delta"):
            return self._page("group", query)
        if url.path.endswith("/groups"):
            prefix = query.get("$filter", "").split("'")[1].replace("''", "'")
            found = [
                {"id": g, "displayName": v["name"]}
                for g, v in self.groups.items()
                if v["name"].lower().startswith(prefix.lower())
            ]
            return httpx.Response(200, json={"value": found})
        return httpx.Response(404)
