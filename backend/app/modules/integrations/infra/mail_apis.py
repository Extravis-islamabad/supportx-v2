"""Reading a mailbox through Microsoft Graph or the Gmail API (WP-024 session 2; REQ-INT-050).

Both readers satisfy the IMAP reader's `MailboxReader`: unread messages oldest first, each as its
raw MIME, so the parser, the ledger and the routing are the same for every kind of mailbox. After
SupportX has stored a message, `done` marks it read, moves it, or deletes it (Graph: to Deleted
Items; Gmail: to Trash, which `gmail.modify` allows), never before (REQ-ADM-067).

Errors become reason codes for the mail page; response bodies are never logged or shown.
"""

import base64
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote

import httpx

from app.modules.integrations.domain.mailboxes import AfterFetch
from app.modules.integrations.infra.imap import (
    FETCH_LIMIT,
    FetchedMessage,
    MailboxUnavailableError,
)
from app.modules.integrations.infra.oauth import (
    OAUTH_CONSENT_REVOKED,
    OAUTH_NOT_ALLOWED,
    OAUTH_UNREACHABLE,
)

FOLDER_NOT_FOUND = "mailbox_folder_not_found"
MAILBOX_NOT_FOUND = "mailbox_not_found_at_provider"


def _reason(response: httpx.Response) -> str:
    if response.status_code == 401:  # noqa: PLR2004 - HTTP status
        return OAUTH_CONSENT_REVOKED
    if response.status_code == 403:  # noqa: PLR2004 - outside the app's scope or policy
        return OAUTH_NOT_ALLOWED
    if response.status_code == 404:  # noqa: PLR2004
        return MAILBOX_NOT_FOUND
    return OAUTH_UNREACHABLE


class _ApiReader:
    """An HTTP session with one access token."""

    def __init__(self, http: httpx.AsyncClient, base: str, access_token: str) -> None:
        self._http = http
        self._base = base
        self._headers = {"Authorization": f"Bearer {access_token}"}

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._http.request(
                method, f"{self._base}{path}", params=params, json=json, headers=self._headers
            )
        except httpx.HTTPError as exc:
            raise MailboxUnavailableError(OAUTH_UNREACHABLE) from exc
        if response.status_code >= 400:  # noqa: PLR2004 - HTTP error range
            raise MailboxUnavailableError(_reason(response))
        return response

    async def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401 - passed through to httpx
        response = await self._call(method, path, **kwargs)
        try:
            body: dict[str, Any] = response.json()  # Any: provider JSON, read field by field
        except ValueError as exc:
            raise MailboxUnavailableError(OAUTH_UNREACHABLE) from exc
        return body

    async def close(self) -> None:
        """End the HTTP session."""
        await self._http.aclose()


def _odata(value: str) -> str:
    """A string literal inside an OData filter (quotes doubled)."""
    return "'" + value.replace("'", "''") + "'"


class GraphReader(_ApiReader):
    """MailboxReader over Microsoft Graph (application or delegated permission)."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        graph_url: str,
        access_token: str,
        *,
        address: str | None,
        folder: str,
    ) -> None:
        # Application permission names the mailbox; delegated sign-in reads "me".
        base = f"{graph_url}/users/{quote(address, safe='@')}" if address else f"{graph_url}/me"
        super().__init__(http, base, access_token)
        self._folder_name = folder
        self._folder_ids: dict[str, str] = {}

    async def _folder(self, name: str) -> str:
        if name.lower() == "inbox":
            return "inbox"  # Graph's well-known name, in every language
        if name not in self._folder_ids:
            found = await self._json(
                "GET",
                "/mailFolders",
                params={"$filter": f"displayName eq {_odata(name)}", "$select": "id"},
            )
            values = found.get("value") or []
            if not values:
                raise MailboxUnavailableError(FOLDER_NOT_FOUND)
            self._folder_ids[name] = str(values[0]["id"])
        return self._folder_ids[name]

    async def new_messages(self, limit: int = FETCH_LIMIT) -> Sequence[FetchedMessage]:
        """Unread messages of the folder, oldest first (reading does not mark them read)."""
        folder = await self._folder(self._folder_name)
        listed = await self._json(
            "GET",
            f"/mailFolders/{folder}/messages",
            params={
                # Graph wants the $orderby property first in $filter.
                "$filter": "receivedDateTime ge 1900-01-01T00:00:00Z and isRead eq false",
                "$orderby": "receivedDateTime asc",
                "$top": str(limit),
                "$select": "id",
            },
        )
        found: list[FetchedMessage] = []
        for item in listed.get("value") or []:
            message_id = str(item["id"])
            raw = await self._call("GET", f"/messages/{quote(message_id, safe='')}/$value")
            found.append(FetchedMessage(message_id, raw.content))
        return found

    async def done(self, uid: str, after: AfterFetch, folder: str | None = None) -> None:
        """Mark read, move to `folder` (read), or delete (to Deleted Items)."""
        path = f"/messages/{quote(uid, safe='')}"
        if after is AfterFetch.DELETE:
            await self._call("DELETE", path)
            return
        await self._call("PATCH", path, json={"isRead": True})
        if after is AfterFetch.MOVE and folder:
            await self._call(
                "POST", f"{path}/move", json={"destinationId": await self._folder(folder)}
            )


class GmailReader(_ApiReader):
    """MailboxReader over the Gmail API (`gmail.modify`; the mailbox's own account)."""

    def __init__(
        self, http: httpx.AsyncClient, gmail_url: str, access_token: str, *, folder: str
    ) -> None:
        super().__init__(http, f"{gmail_url}/users/me", access_token)
        self._folder_name = folder
        self._label_ids: dict[str, str] = {}

    async def _label(self, name: str) -> str:
        if name.upper() == "INBOX":
            return "INBOX"
        if name not in self._label_ids:
            labels = await self._json("GET", "/labels")
            for label in labels.get("labels") or []:
                self._label_ids[str(label.get("name"))] = str(label.get("id"))
            if name not in self._label_ids:
                raise MailboxUnavailableError(FOLDER_NOT_FOUND)
        return self._label_ids[name]

    async def new_messages(self, limit: int = FETCH_LIMIT) -> Sequence[FetchedMessage]:
        """Unread messages with the folder's label, oldest first."""
        label = await self._label(self._folder_name)
        listed = await self._json(
            "GET",
            "/messages",
            params={"labelIds": label, "q": "is:unread", "maxResults": str(limit)},
        )
        found: list[FetchedMessage] = []
        # Gmail lists newest first; the oldest are handled first, as for IMAP.
        for item in reversed(listed.get("messages") or []):
            message_id = str(item["id"])
            body = await self._json(
                "GET", f"/messages/{quote(message_id, safe='')}", params={"format": "raw"}
            )
            raw = str(body.get("raw", ""))
            found.append(
                FetchedMessage(message_id, base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
            )
        return found

    async def done(self, uid: str, after: AfterFetch, folder: str | None = None) -> None:
        """Mark read, move to the `folder` label (read, out of the inbox), or trash it."""
        path = f"/messages/{quote(uid, safe='')}"
        if after is AfterFetch.DELETE:
            await self._call("POST", f"{path}/trash")
            return
        change: dict[str, list[str]] = {"removeLabelIds": ["UNREAD"]}
        if after is AfterFetch.MOVE and folder:
            change = {
                "addLabelIds": [await self._label(folder)],
                "removeLabelIds": ["UNREAD", await self._label(self._folder_name)],
            }
        await self._call("POST", f"{path}/modify", json=change)


async def account_address(
    http: httpx.AsyncClient, *, graph_url: str | None, gmail_url: str | None, access_token: str
) -> str:
    """The address of the account that signed in (it must be the mailbox's own)."""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        if gmail_url is not None:
            response = await http.get(f"{gmail_url}/users/me/profile", headers=headers)
            key = "emailAddress"
        else:
            response = await http.get(
                f"{graph_url}/me", params={"$select": "mail,userPrincipalName"}, headers=headers
            )
            key = "mail"
    except httpx.HTTPError as exc:
        raise MailboxUnavailableError(OAUTH_UNREACHABLE) from exc
    if response.status_code >= 400:  # noqa: PLR2004 - HTTP error range
        raise MailboxUnavailableError(_reason(response))
    try:
        body = response.json()
    except ValueError as exc:
        raise MailboxUnavailableError(OAUTH_UNREACHABLE) from exc
    return str(body.get(key) or body.get("userPrincipalName") or "").lower()
