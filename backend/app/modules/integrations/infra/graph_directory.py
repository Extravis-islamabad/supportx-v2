"""Microsoft Graph as a directory: users and group members by delta query (WP-040 session 2).

The customer's own sync app (a separate app from the mail one, so each holds least privilege;
WP-040 plan decision 2) holds the application permissions `User.Read.All` and
`GroupMember.Read.All` only, and gets its token by client credentials (`OAuth.app_token`).

A delta round reads every `@odata.nextLink` page until Graph hands back an `@odata.deltaLink`;
the next round starts from that link and receives only what changed. An expired link (410) means
start again from the beginning, which is safe: applying a person twice changes nothing.

Like the mail readers, nothing here logs a token or a response body; a refusal becomes a reason
code (`oauth_*`, `directory_*`) the connector page shows.
"""

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from app.modules.integrations.domain.directory import PAGE_SIZE
from app.modules.integrations.infra.oauth import (
    OAUTH_CERTIFICATE_INVALID,
    OAUTH_CLIENT_REJECTED,
    OAUTH_CONSENT_REVOKED,
    OAUTH_NOT_ALLOWED,
    OAUTH_UNREACHABLE,
)

GRAPH_SCOPE = "https://graph.microsoft.com/.default"  # the app's granted application permissions
DELTA_EXPIRED = "directory_delta_expired"  # 410 Gone: the round restarts from the beginning
GROUP_NOT_FOUND = "directory_group_not_found"
# A delta round of 100,000 people is ~100 pages; this stops a provider loop, not a real tenant.
MAX_PAGES = 2_000
MAX_THROTTLE_RETRIES = 3
MAX_RETRY_AFTER_SECONDS = 30.0


class DirectoryUnavailableError(Exception):
    """The directory refused or failed; `code` says what an admin can do about it."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    @property
    def auth_failure(self) -> bool:
        """Whether the directory refused the app itself (failing at once, D-118 defaults)."""
        return self.code in {
            OAUTH_CONSENT_REVOKED,
            OAUTH_NOT_ALLOWED,
            OAUTH_CLIENT_REJECTED,
            OAUTH_CERTIFICATE_INVALID,
        }


@dataclass
class DeltaPage:
    """One page of a delta round; `delta_link` is set on the last page only."""

    items: Sequence[Mapping[str, Any]]  # Any: Graph JSON, read field by field in the domain
    delta_link: str | None


def _reason(response: httpx.Response) -> str:
    if response.status_code == 401:  # noqa: PLR2004 - HTTP status
        return OAUTH_CONSENT_REVOKED
    if response.status_code == 403:  # noqa: PLR2004 - permission not granted or not consented
        return OAUTH_NOT_ALLOWED
    if response.status_code == 404:  # noqa: PLR2004 - a chosen group was deleted
        return GROUP_NOT_FOUND
    if response.status_code == 410:  # noqa: PLR2004 - the delta link expired
        return DELTA_EXPIRED
    return OAUTH_UNREACHABLE


def _retry_after(response: httpx.Response) -> float:
    try:
        return min(float(response.headers.get("Retry-After", "5")), MAX_RETRY_AFTER_SECONDS)
    except ValueError:
        return 5.0


class GraphDirectory:
    """Delta reads with one access token. `sleep` is replaceable so tests do not wait."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        base: str,
        access_token: str,
        *,
        sleep: Any = asyncio.sleep,  # noqa: ANN401 - an awaitable sleep(seconds)
    ) -> None:
        self._http = http
        self._base = base.rstrip("/")
        # Changed properties only, full pages (fewer calls under throttling).
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Prefer": f"return=minimal, odata.maxpagesize={PAGE_SIZE}",
        }
        self._sleep = sleep

    async def _get(self, url: str, params: Mapping[str, str] | None) -> Mapping[str, Any]:
        for _attempt in range(MAX_THROTTLE_RETRIES + 1):
            try:
                response = await self._http.get(url, params=params, headers=self._headers)
            except httpx.HTTPError as exc:
                raise DirectoryUnavailableError(OAUTH_UNREACHABLE) from exc
            if response.status_code in {429, 503}:  # throttled: Graph says how long to wait
                await self._sleep(_retry_after(response))
                continue
            if response.status_code >= 400:  # noqa: PLR2004 - HTTP error range
                raise DirectoryUnavailableError(_reason(response))
            try:
                body: Mapping[str, Any] = response.json()
            except ValueError as exc:
                raise DirectoryUnavailableError(OAUTH_UNREACHABLE) from exc
            return body
        raise DirectoryUnavailableError(OAUTH_UNREACHABLE)

    def _own(self, link: str) -> str:
        # Follow only Graph's own links: a link to elsewhere would send the token there.
        if not link.startswith(f"{self._base}/"):
            raise DirectoryUnavailableError(OAUTH_UNREACHABLE)
        return link

    async def _rounds(
        self, first: str, params: Mapping[str, str] | None
    ) -> AsyncIterator[DeltaPage]:
        url, query = first, params
        for _page in range(MAX_PAGES):
            body = await self._get(url, query)
            items = body.get("value")
            values = [i for i in items if isinstance(i, Mapping)] if isinstance(items, list) else []
            following, final = body.get("@odata.nextLink"), body.get("@odata.deltaLink")
            if isinstance(following, str):
                yield DeltaPage(values, None)
                url, query = self._own(following), None  # the link carries the query
                continue
            yield DeltaPage(values, self._own(final) if isinstance(final, str) else None)
            return
        raise DirectoryUnavailableError(OAUTH_UNREACHABLE)

    def users(self, link: str | None, select: str) -> AsyncIterator[DeltaPage]:
        """Changed users since `link` (every user when None)."""
        if link is not None:
            return self._rounds(self._own(link), None)
        return self._rounds(f"{self._base}/users/delta", {"$select": select})

    def groups(self, link: str | None, group_ids: Sequence[str]) -> AsyncIterator[DeltaPage]:
        """Changed members of the given groups since `link` (`members@delta` on each group)."""
        if link is not None:
            return self._rounds(self._own(link), None)
        ids = ",".join(f"'{g}'" for g in group_ids if _is_graph_id(g))
        return self._rounds(
            f"{self._base}/groups/delta",
            {"$select": "displayName,members", "$filter": f"id in ({ids})"},
        )

    async def group_names(self, query: str) -> list[tuple[str, str]]:
        """(id, name) of up to 25 groups whose name starts with `query`, for the mapping screen."""
        safe = query.replace("'", "''")[:100]
        body = await self._get(
            f"{self._base}/groups",
            {
                "$select": "id,displayName",
                "$top": "25",
                "$filter": f"startswith(displayName,'{safe}')",
            },
        )
        found = body.get("value")
        return [
            (str(g["id"]), str(g.get("displayName") or ""))
            for g in (found if isinstance(found, list) else [])
            if isinstance(g, Mapping) and isinstance(g.get("id"), str)
        ]

    async def close(self) -> None:
        """End the HTTP session."""
        await self._http.aclose()


def _is_graph_id(value: str) -> bool:
    # Graph object IDs are GUIDs; anything else never reaches a $filter.
    parts = value.split("-")
    return [len(p) for p in parts] == [8, 4, 4, 4, 12] and all(
        c in "0123456789abcdefABCDEF" for p in parts for c in p
    )
