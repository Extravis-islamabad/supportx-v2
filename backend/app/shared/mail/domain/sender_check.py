"""Whether an incoming message's sender is verified (WP-046a S6; REQ-INC-025). Pure, no I/O.

`From:` is forgeable, so commands written in an e-mail (`priority = p1`) are honoured only when the
receiving mail server vouched for the sender in its `Authentication-Results` header (RFC 8601):
DMARC passed for the From domain, or SPF passed and a DKIM signature of an aligned domain passed.

Only the server the admin named is believed (lane B's conditions, #S6):

1. Only `Authentication-Results` headers whose authserv-id the mailbox trusts count, and of those
   only the topmost: a header further down may have come with the message. Should a lower trusted
   header disagree with it, nothing is verified.
2. `trust_provider` (Microsoft 365 through Graph only): Microsoft writes its header without an
   authserv-id; with the switch on, only the topmost header, and only when it has no authserv-id.
3. Exactly one `From:` header holding exactly one address; a DMARC pass must name that domain.
4. Alignment without the Public Suffix List: the same domain, or one a subdomain of the other at
   a dot boundary. Sibling subdomains do not align.
5. Any doubt (too many or too long headers, unbalanced comments, unreadable values): not verified.
6. `ARC-Authentication-Results` and `Authentication-Results-Original` are never read: they
   report what another hop saw, not what our server checked.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from email.message import Message
from email.utils import getaddresses

HEADER = "Authentication-Results"
MAX_HEADERS = 20  # more than this many results headers: not verified
MAX_HEADER_LENGTH = 8_000  # characters of one unfolded header
TRUSTED_MAX = 5  # names a mailbox may trust


class Unreadable(ValueError):
    """A header that cannot be read with certainty."""


@dataclass(frozen=True)
class Result:
    """One `method=result` with its properties (`header.from`, `header.d`…), all lowercased."""

    method: str
    result: str
    properties: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Header:
    """One `Authentication-Results` header: who wrote it (None: no authserv-id) and its results."""

    authserv_id: str | None
    results: tuple[Result, ...]


def _quoted_end(value: str, start: int) -> int:
    """The index just past the quoted string opening at `start` (backslash escapes kept)."""
    index = start + 1
    while index < len(value):
        if value[index] == "\\":
            index += 2
            continue
        if value[index] == '"':
            return index + 1
        index += 1
    raise Unreadable(value)


def _comment_end(value: str, start: int) -> int:
    """The index just past the (comment) opening at `start`, nested comments included."""
    depth, index = 0, start
    while index < len(value):
        char = value[index]
        if char == "\\":
            index += 2
            continue
        depth += {"(": 1, ")": -1}.get(char, 0)
        index += 1
        if depth == 0:
            return index
    raise Unreadable(value)


def _uncommented(value: str) -> str:
    """The value without (comments), nested ones too; quoted strings kept as they are."""
    out: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "(":
            index = _comment_end(value, index)
        elif char == ")":
            raise Unreadable(value)
        elif char == '"':
            end = _quoted_end(value, index)
            out.append(value[index:end])
            index = end
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _segments(value: str) -> list[list[str]]:
    """The `;`-separated segments of a value, each a list of space-separated tokens.

    One quote-aware pass (lane B's review of #485): a quoted string is part of its token whatever
    it holds, `;` and spaces included, with the same escapes as `_quoted_end`.
    """
    segments: list[list[str]] = [[]]
    token: list[str] = []

    def close_token() -> None:
        if token:
            segments[-1].append("".join(token))
            token.clear()

    index = 0
    while index < len(value):
        char = value[index]
        if char == '"':
            end = _quoted_end(value, index)
            token.append(value[index:end])
            index = end
            continue
        if char == ";":
            close_token()
            segments.append([])
        elif char.isspace():
            close_token()
        else:
            token.append(char)
        index += 1
    close_token()
    return segments


def _unquoted(value: str) -> str:
    """A property's value: a whole quoted string unescaped, or a bare word with no quotes."""
    if value.startswith('"'):
        if len(value) < 2 or _quoted_end(value, 0) != len(value):  # noqa: PLR2004 - two quotes
            raise Unreadable(value)
        inner, out, index = value[1:-1], [], 0
        while index < len(inner):
            if inner[index] == "\\" and index + 1 < len(inner):
                index += 1
            out.append(inner[index])
            index += 1
        return "".join(out)
    if '"' in value:
        raise Unreadable(value)
    return value


def _pair(token: str) -> tuple[str, str]:
    """`name=value`; anything else (a stray word, an empty side) is unreadable."""
    name, sep, value = token.partition("=")
    if not sep or not name or not value or '"' in name:
        raise Unreadable(token)
    return name.lower(), _unquoted(value).lower()


def _result(tokens: list[str]) -> Result | None:
    if not tokens or tokens == ["none"]:  # RFC 8601: "none" is no results at all
        return None
    method, result = _pair(tokens[0])
    method = method.split("/", 1)[0]  # "dkim/1" → "dkim"
    properties: dict[str, str] = {}
    for token in tokens[1:]:
        name, value = _pair(token)  # raises on a stray word: never skipped silently
        if "." not in name:  # reason=, action= and other extensions: read, never used
            continue
        if name in properties:  # a second header.d after the first: which one is meant?
            raise Unreadable(token)
        properties[name] = value
    return Result(method, result, properties)


def read_header(value: str) -> Header:
    """One unfolded `Authentication-Results` value."""
    if len(value) > MAX_HEADER_LENGTH:
        raise Unreadable(value[:80])
    segments = _segments(_uncommented(value))
    first = segments[0]
    if not first:
        raise Unreadable(value)
    if "=" in first[0]:  # Microsoft 365: results without an authserv-id
        authserv_id, rest = None, segments
    else:
        if len(first) > 2 or (len(first) == 2 and not first[1].isdigit()):  # noqa: PLR2004 - id [version]
            raise Unreadable(value)
        authserv_id, rest = first[0].lower().rstrip("."), segments[1:]
    results = tuple(r for r in (_result(s) for s in rest) if r is not None)
    return Header(authserv_id, results)


def aligned(signer: str, author: str) -> bool:
    """Same domain, or one a subdomain of the other at a dot boundary (no Public Suffix List)."""
    a, b = signer.lower().rstrip("."), author.lower().rstrip(".")
    if not a or not b:
        return False
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def _domain(address: str) -> str:
    local, at, domain = address.rpartition("@")
    return domain.lower().rstrip(".") if at and local and "." in domain else ""


def from_domain(message: Message) -> str | None:
    """The single author's domain, or None unless there is exactly one From with one address."""
    headers = message.get_all("From") or []
    if len(headers) != 1:
        return None
    try:
        addresses = [a for _, a in getaddresses([str(headers[0])]) if a]
    except (TypeError, ValueError):
        return None
    if len(addresses) != 1:
        return None
    return _domain(addresses[0]) or None


def _signer(result: Result) -> str:
    domain = result.properties.get("header.d", "")
    if not domain:  # some servers give only the identity: "header.i=@example.com"
        domain = result.properties.get("header.i", "").rpartition("@")[2]
    return domain


def passes(header: Header, author: str) -> bool:
    """DMARC passed for the author's domain, or SPF passed with an aligned DKIM pass."""
    for result in header.results:
        if (result.method, result.result) == ("dmarc", "pass") and (
            result.properties.get("header.from", "").rstrip(".") == author
        ):
            return True
    spf = any(r.method == "spf" and r.result == "pass" for r in header.results)
    dkim = any(
        r.method == "dkim" and r.result == "pass" and aligned(_signer(r), author)
        for r in header.results
    )
    return spf and dkim


def _verdicts(
    values: Sequence[object], names: set[str], *, trust_provider: bool, author: str
) -> list[bool] | None:
    """Each believed header's verdict, topmost first; None when anything is in doubt."""
    verdicts: list[bool] = []
    for index, value in enumerate(values):
        try:
            header = read_header(str(value))
        except Unreadable:
            # We cannot tell who wrote it, and our server's own header is always readable: so
            # nothing may be believed.
            return None
        if header.authserv_id is None:
            if not trust_provider:
                continue
            if index != 0:  # Microsoft's own header is the topmost; a lower one came with the mail
                return None
            verdicts.append(passes(header, author))
        elif header.authserv_id in names:
            verdicts.append(passes(header, author))
    return verdicts


def sender_verified(
    message: Message, *, trusted: Sequence[str], trust_provider: bool = False
) -> bool:
    """Whether the server the mailbox trusts vouched for the sender (see the module docstring)."""
    names = {name.lower().rstrip(".") for name in trusted if name}
    author = from_domain(message)
    values = message.get_all(HEADER) or []
    if (not names and not trust_provider) or author is None or len(values) > MAX_HEADERS:
        return False
    verdicts = _verdicts(values, names, trust_provider=trust_provider, author=author)
    # The topmost believed header decides, and no lower believed header may disagree.
    return verdicts is not None and bool(verdicts) and all(verdicts)
