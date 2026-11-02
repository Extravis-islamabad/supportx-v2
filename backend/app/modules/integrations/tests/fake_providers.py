"""A fake Microsoft identity platform + Graph and Google OAuth + Gmail, for tests (WP-024 s2).

An `httpx.MockTransport`: no network, no real account. It keeps mailboxes of raw messages,
issues tokens for known clients, and checks what the real services check that matters here:
the client's secret or signed assertion, PKCE, the redirect address, and the bearer token.
"""

import base64
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

LOGIN = "https://login.test"
GRAPH = "https://graph.test/v1.0"
GOOGLE_AUTHORIZE = "https://accounts.test/auth"
GOOGLE_TOKEN = "https://oauth.test/token"
GMAIL = "https://gmail.test/gmail/v1"


@dataclass
class Message:
    """A message in a fake mailbox."""

    raw: bytes
    unread: bool = True
    folder: str = "inbox"
    deleted: bool = False


@dataclass
class FakeProviders:
    """The fake's state; tests read and change it."""

    client_id: str = "app-1"
    client_secret: str = "s3cret"
    public_key: rsa.RSAPublicKey | None = None  # set: certificate assertions are accepted
    mailboxes: dict[str, list[Message]] = field(default_factory=dict)  # address -> messages
    folders: dict[str, str] = field(default_factory=lambda: {"Done": "folder-done"})
    # Authorization codes issued by "signing in": code -> (account, PKCE challenge, redirect).
    codes: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    refresh_tokens: dict[str, str] = field(default_factory=dict)  # token -> account
    access_tokens: dict[str, str | None] = field(default_factory=dict)  # token -> account|None
    rotate: bool = False  # Microsoft-style: a new refresh token each time
    refuse_with: str | None = None  # the token endpoint answers this OAuth error
    allowed: set[str] | None = None  # app permission limited to these mailboxes (RBAC)
    requests: list[httpx.Request] = field(default_factory=list)

    def transport(self) -> httpx.MockTransport:
        """The httpx transport to install (connections.use_transport)."""
        return httpx.MockTransport(self._handle)

    def sign_in(self, account: str, authorize_url: str) -> tuple[str, str]:
        """What the browser does at the provider: (state, code) for the callback."""
        query = {k: v[0] for k, v in parse_qs(urlsplit(authorize_url).query).items()}
        assert query["client_id"] == self.client_id
        assert query["code_challenge_method"] == "S256"
        code = f"code-{uuid.uuid4().hex}"
        self.codes[code] = (account, query["code_challenge"], query["redirect_uri"])
        return query["state"], code

    def deliver(self, address: str, raw: bytes) -> None:
        """A message arrives in the mailbox."""
        self.mailboxes.setdefault(address.lower(), []).append(Message(raw))

    # --- the token endpoints ------------------------------------------------------------------

    def _client_ok(self, form: dict[str, str], token_url: str) -> bool:
        if form.get("client_id") != self.client_id:
            return False
        if "client_secret" in form:
            return form["client_secret"] == self.client_secret
        assertion = form.get("client_assertion")
        if assertion is None or self.public_key is None:
            return False
        head, claims, signature = assertion.split(".")
        padded = signature + "=" * (-len(signature) % 4)
        try:
            self.public_key.verify(
                base64.urlsafe_b64decode(padded),
                f"{head}.{claims}".encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except Exception:  # noqa: BLE001 - any verification failure is a refusal
            return False
        body = json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))
        return bool(body["aud"] == token_url and body["iss"] == self.client_id)

    def _issue(self, account: str | None, *, refresh: bool) -> dict[str, object]:
        access = f"at-{uuid.uuid4().hex}"
        self.access_tokens[access] = account
        body: dict[str, object] = {"access_token": access, "expires_in": 3600}
        if refresh and account is not None:
            token = f"rt-{uuid.uuid4().hex}"
            self.refresh_tokens[token] = account
            body["refresh_token"] = token
        return body

    def _token(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911 - one answer per grant
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if self.refuse_with:
            return httpx.Response(400, json={"error": self.refuse_with, "error_description": "x"})
        if not self._client_ok(form, str(request.url)):
            return httpx.Response(401, json={"error": "invalid_client"})
        grant = form.get("grant_type")
        if grant == "client_credentials":
            return httpx.Response(200, json=self._issue(None, refresh=False))
        if grant == "authorization_code":
            found = self.codes.pop(form.get("code", ""), None)
            if found is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            account, challenge, redirect = found
            verifier = form.get("code_verifier", "")
            digest = hashlib.sha256(verifier.encode()).digest()
            computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            if computed != challenge or form.get("redirect_uri") != redirect:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=self._issue(account, refresh=True))
        if grant == "refresh_token":
            holder = self.refresh_tokens.get(form.get("refresh_token", ""))
            if holder is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            if self.rotate:
                del self.refresh_tokens[form["refresh_token"]]
            return httpx.Response(200, json=self._issue(holder, refresh=self.rotate))
        return httpx.Response(400, json={"error": "unsupported_grant_type"})

    # --- the mail APIs -------------------------------------------------------------------------

    def _account(self, request: httpx.Request) -> tuple[bool, str | None]:
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token not in self.access_tokens:
            return False, None
        return True, self.access_tokens[token]

    def _graph(self, request: httpx.Request, path: str) -> httpx.Response:  # noqa: C901, PLR0911, PLR0912 - one branch per Graph call
        known, account = self._account(request)
        if not known:
            return httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken"}})
        parts = path.strip("/").split("/")
        if parts[0] == "me":
            if account is None:
                return httpx.Response(400)
            if len(parts) == 1:
                return httpx.Response(200, json={"mail": account, "userPrincipalName": account})
            address, rest = account, parts[1:]
        else:  # users/{address}/...: application permission
            address, rest = unquote(parts[1]).lower(), parts[2:]
            if account is not None or (self.allowed is not None and address not in self.allowed):
                return httpx.Response(403, json={"error": {"code": "ErrorAccessDenied"}})
        messages = self.mailboxes.get(address)
        if messages is None:
            return httpx.Response(404, json={"error": {"code": "ErrorInvalidUser"}})
        if rest == ["mailFolders"]:
            name = parse_qs(urlsplit(str(request.url)).query)["$filter"][0].split("'")[1]
            found = [{"id": self.folders[name]}] if name in self.folders else []
            return httpx.Response(200, json={"value": found})
        if rest[0] == "mailFolders" and rest[2] == "messages":
            folder = rest[1]
            top = int(parse_qs(urlsplit(str(request.url)).query)["$top"][0])
            listed = [
                {"id": str(i)}
                for i, m in enumerate(messages)
                if m.unread and not m.deleted and m.folder == folder
            ][:top]
            return httpx.Response(200, json={"value": listed})
        message = messages[int(rest[1])]
        if len(rest) == 3 and rest[2] == "$value":
            return httpx.Response(200, content=message.raw)
        if len(rest) == 3 and rest[2] == "move":
            message.folder = json.loads(request.content)["destinationId"]
            return httpx.Response(201, json={"id": rest[1]})
        if request.method == "PATCH":
            message.unread = not json.loads(request.content)["isRead"]
            return httpx.Response(200, json={"id": rest[1]})
        if request.method == "DELETE":
            message.deleted = True
            return httpx.Response(204)
        return httpx.Response(400)

    def _gmail(self, request: httpx.Request, path: str) -> httpx.Response:  # noqa: PLR0911 - one branch per Gmail call
        known, account = self._account(request)
        if not known or account is None:
            return httpx.Response(401, json={"error": {"status": "UNAUTHENTICATED"}})
        rest = path.strip("/").split("/")[2:]  # users/me/...
        messages = self.mailboxes.setdefault(account, [])
        if rest == ["profile"]:
            return httpx.Response(200, json={"emailAddress": account})
        if rest == ["labels"]:
            labels = [{"id": "INBOX", "name": "INBOX"}] + [
                {"id": label_id, "name": name} for name, label_id in self.folders.items()
            ]
            return httpx.Response(200, json={"labels": labels})
        if rest == ["messages"]:
            query = parse_qs(urlsplit(str(request.url)).query)
            label = query["labelIds"][0]
            folder = "inbox" if label == "INBOX" else label
            listed = [
                {"id": str(i)}
                for i, m in enumerate(messages)
                if m.unread and not m.deleted and m.folder == folder
            ]
            listed.reverse()  # Gmail: newest first
            return httpx.Response(200, json={"messages": listed[: int(query["maxResults"][0])]})
        message = messages[int(rest[1])]
        if len(rest) == 2:
            raw = base64.urlsafe_b64encode(message.raw).rstrip(b"=").decode()
            return httpx.Response(200, json={"id": rest[1], "raw": raw})
        if rest[2] == "trash":
            message.deleted = True
            return httpx.Response(200, json={"id": rest[1]})
        change = json.loads(request.content)
        if "UNREAD" in change.get("removeLabelIds", []):
            message.unread = False
        for label in change.get("addLabelIds", []):
            message.folder = label
        return httpx.Response(200, json={"id": rest[1]})

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith(LOGIN) and url.split("?", maxsplit=1)[0].endswith("/token"):
            return self._token(request)
        if url.startswith(GOOGLE_TOKEN):
            return self._token(request)
        if url.startswith(GRAPH):
            return self._graph(request, urlsplit(url).path.removeprefix("/v1.0"))
        if url.startswith(GMAIL):
            return self._gmail(request, urlsplit(url).path.removeprefix("/gmail/v1"))
        return httpx.Response(404)


def endpoint_settings() -> dict[str, str]:
    """Settings that point SupportX at the fake (Settings(**...) keyword arguments)."""
    return {
        "mail_microsoft_login_url": LOGIN,
        "mail_graph_url": GRAPH,
        "mail_google_authorize_url": GOOGLE_AUTHORIZE,
        "mail_google_token_url": GOOGLE_TOKEN,
        "mail_gmail_url": GMAIL,
    }
