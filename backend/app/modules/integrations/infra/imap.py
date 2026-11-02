"""Reading a mailbox over IMAP (WP-024; REQ-INT-050, REQ-ADM-067).

The standard library's `imaplib`, run in a worker thread (it blocks). TLS by default (IMAPS 993
or STARTTLS); a plain connection only when the mailbox allows it (the service checks and audits).

`new_messages()` returns unseen messages with their UID; after SupportX has stored a message (and
its effect) in one transaction, `done(uid)` marks it read, moves it, or deletes it, as the
mailbox says. A crash between the two leaves the message unseen on the server: the next fetch
finds it again, and the ledger (`mail_fetched`) skips it, so nothing is created twice.
"""

import asyncio
import contextlib
import imaplib
import re
import ssl
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.modules.integrations.domain.mailboxes import AfterFetch, ConnectionSecurity

TIMEOUT_SECONDS = 30.0
IMAP_LOGIN_FAILED = "imap_login_failed"
IMAP_TLS_FAILED = "imap_tls_failed"
IMAP_UNREACHABLE = "imap_unreachable"
FETCH_LIMIT = 50  # messages per fetch; the rest wait for the next poll


class MailboxUnavailableError(Exception):
    """The mail server could not be reached or refused us; `reason` is a code for the mail page."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ImapSettings:
    """How to reach one mailbox."""

    host: str
    port: int
    security: ConnectionSecurity
    username: str
    password: str
    folder: str = "INBOX"


@dataclass(frozen=True)
class FetchedMessage:
    """A message as the server holds it."""

    uid: str
    raw: bytes


class MailboxReader(Protocol):
    """What the fetch service needs from a mailbox (IMAP now; Graph and Gmail later)."""

    async def new_messages(self, limit: int = FETCH_LIMIT) -> Sequence[FetchedMessage]:
        """Unseen messages, oldest first."""
        ...

    async def done(self, uid: str, after: AfterFetch, folder: str | None = None) -> None:
        """Mark read, move to `folder`, or delete, as the mailbox says."""
        ...

    async def close(self) -> None:
        """End the session."""
        ...


def _check(status: str, what: str) -> None:
    if status != "OK":
        reason = f"imap_{what}_failed"
        raise MailboxUnavailableError(reason)


class ImapReader:
    """MailboxReader over imaplib (one connection per fetch)."""

    def __init__(self, settings: ImapSettings) -> None:
        self.settings = settings
        self._client: imaplib.IMAP4 | None = None

    def _connect(self) -> imaplib.IMAP4:
        s = self.settings
        context = ssl.create_default_context()
        try:
            if s.security is ConnectionSecurity.TLS:
                client: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                    s.host, s.port, ssl_context=context, timeout=TIMEOUT_SECONDS
                )
            else:
                client = imaplib.IMAP4(s.host, s.port, timeout=TIMEOUT_SECONDS)
                if s.security is ConnectionSecurity.STARTTLS:
                    client.starttls(ssl_context=context)
            client.login(s.username, s.password)
        except imaplib.IMAP4.error as exc:
            raise MailboxUnavailableError(IMAP_LOGIN_FAILED) from exc
        except ssl.SSLError as exc:
            raise MailboxUnavailableError(IMAP_TLS_FAILED) from exc
        except OSError as exc:
            raise MailboxUnavailableError(IMAP_UNREACHABLE) from exc
        status, _ = client.select(_quote(s.folder))
        _check(status, "select")
        return client

    def _client_now(self) -> imaplib.IMAP4:
        if self._client is None:
            self._client = self._connect()
        return self._client

    def _new_messages(self, limit: int) -> list[FetchedMessage]:
        client = self._client_now()
        status, data = client.uid("SEARCH", "UNSEEN")
        _check(status, "search")
        uids = (data[0] or b"").split()[:limit] if data else []
        found: list[FetchedMessage] = []
        for raw_uid in uids:
            uid = raw_uid.decode() if isinstance(raw_uid, bytes) else str(raw_uid)
            # BODY.PEEK: reading does not mark the message seen; `done` decides that.
            status, parts = client.uid("FETCH", uid, "(BODY.PEEK[])")
            _check(status, "fetch")
            raw = next(
                (p[1] for p in parts if isinstance(p, tuple) and isinstance(p[1], bytes)), None
            )
            if raw is not None:
                found.append(FetchedMessage(uid, raw))
        return found

    def _done(self, uid: str, after: AfterFetch, folder: str | None) -> None:
        client = self._client_now()
        if after is AfterFetch.MOVE and folder:
            status, _ = client.uid("COPY", uid, _quote(folder))
            _check(status, "move")
            client.uid("STORE", uid, "+FLAGS.SILENT", r"(\Deleted \Seen)")
            client.expunge()
        elif after is AfterFetch.DELETE:
            client.uid("STORE", uid, "+FLAGS.SILENT", r"(\Deleted)")
            client.expunge()
        else:
            status, _ = client.uid("STORE", uid, "+FLAGS.SILENT", r"(\Seen)")
            _check(status, "mark")

    def _close(self) -> None:
        if self._client is not None:
            with contextlib.suppress(imaplib.IMAP4.error, OSError):
                self._client.logout()
            self._client = None

    async def new_messages(self, limit: int = FETCH_LIMIT) -> Sequence[FetchedMessage]:
        """Unseen messages, oldest first (without marking them seen)."""
        try:
            return await asyncio.to_thread(self._new_messages, limit)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailboxUnavailableError(IMAP_UNREACHABLE) from exc

    async def done(self, uid: str, after: AfterFetch, folder: str | None = None) -> None:
        """Mark read, move, or delete the message on the server."""
        try:
            await asyncio.to_thread(self._done, uid, after, folder)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailboxUnavailableError(IMAP_UNREACHABLE) from exc

    async def close(self) -> None:
        """Log out."""
        await asyncio.to_thread(self._close)


def _quote(folder: str) -> str:
    """A folder name as IMAP wants it (quoted; no line breaks or quotes inside)."""
    clean = re.sub(r'["\\\r\n]', "", folder)
    return f'"{clean}"'
