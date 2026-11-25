"""The web image's nginx sends HSTS on every HTML and asset response (audit row 15).

nginx's trap: a block with its own `add_header` drops every `add_header` it would inherit. So
the server block must set HSTS, with the API's value, and any location that adds a header of its
own must set HSTS again (deploy/images/nginx.conf).
"""

import re
from pathlib import Path

from app.core.middleware import HSTS

NGINX_CONF = Path(__file__).resolve().parents[2] / "deploy/images/nginx.conf"
# Quoted or not (`add_header Cache-Control $supportx_cache`), at a line's start or after another
# directive on the same line.
_ADD_HEADER = re.compile(r"(?:^|;)\s*add_header\s+(\S+)\s+(\"[^\"]*\"|[^\s;]+)", re.MULTILINE)


def _blocks(text: str) -> tuple[str, list[tuple[str, str]]]:
    """The server block's own lines, and (head, body) of every location block inside it."""
    text = re.sub(r"#[^\n]*", "", text)
    server_at = text.index("server {")
    own: list[str] = []
    locations: list[tuple[str, str]] = []
    depth, start, head = 0, 0, ""
    line_start = server_at
    for index in range(server_at, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
            if depth == 2:
                head = text[line_start:index].strip()
                start = index + 1
        elif char == "}":
            if depth == 2:
                locations.append((head, text[start:index]))
            depth -= 1
            if depth == 0:
                break
        elif char in ";\n" and depth == 1:
            own.append(text[line_start : index + 1])
        if char in ";{}\n":
            line_start = index + 1
    return "".join(own), locations


def _headers(body: str) -> dict[str, str]:
    return {name.lower(): value.strip('"') for name, value in _ADD_HEADER.findall(body)}


def test_the_server_sends_the_apis_hsts() -> None:
    server, _ = _blocks(NGINX_CONF.read_text(encoding="utf-8"))
    name, value = HSTS
    assert _headers(server)[name.lower()] == value
    assert re.search(rf"add_header\s+{name}\s+\"{re.escape(value)}\"\s+always;", server)


def test_every_location_with_its_own_headers_sends_hsts_too() -> None:
    _, locations = _blocks(NGINX_CONF.read_text(encoding="utf-8"))
    assert any(head.startswith("location /portal/") for head, _ in locations)  # parsed
    name, value = HSTS
    for head, body in locations:
        own = _headers(body)
        if own:
            assert own.get(name.lower()) == value, head


def _map(text: str, variable: str) -> dict[str, str]:
    """One `map <source> $variable { key value; ... }` block's entries."""
    found = re.search(r"map \S+ \$" + variable + r" \{(.*?)\n\}", text, re.DOTALL)
    assert found is not None, variable
    body = re.sub(r"#[^\n]*", "", found.group(1))
    return {
        key: value.strip('"')
        for key, value in re.findall(r"^\s*(\S+)\s+(\"[^\"]*\"|\S+);", body, re.MULTILINE)
    }


def test_the_vendor_support_link_page_is_never_cached_and_sends_no_referer() -> None:
    """WP-057 S4c-3, lane B (2): the page shows a password once; every other page as before.

    The page is matched on $request_uri (the path as asked, with or without a query or a
    trailing slash), never $uri: the SPA fallback rewrites $uri to /index.html before the
    headers go out. Checked against a running nginx by hand (S4c-3 PR); here, the config.
    """
    text = NGINX_CONF.read_text()
    assert re.search(r"map \$request_uri \$supportx_vendor_page \{", text)
    page = _map(text, "supportx_vendor_page")
    pattern = next(k for k, v in page.items() if v == "1").removeprefix("~")
    for asked in (
        "/vendor-support/start",
        "/vendor-support/start?t=acme",
        "/vendor-support/start/",
    ):
        assert re.match(pattern, asked), asked
    for other in ("/vendor-support/started", "/", "/incidents", "/vendor-support/start/x"):
        assert not re.match(pattern, other), other
    assert page["default"] == "0"
    cache = _map(text, "supportx_cache")
    assert cache["~^1:"] == "no-store"
    assert cache["default"] == "no-cache"
    assert _map(text, "supportx_referrer") == {
        "1": "no-referrer",
        "default": "strict-origin-when-cross-origin",
    }
    server, _ = _blocks(text)
    headers = _headers(server)
    assert headers["referrer-policy"] == "$supportx_referrer"
    assert headers["cache-control"] == "$supportx_cache"
    # The CSP keeps scripts same-origin, with no inline script and no third party.
    csp = headers["content-security-policy"]
    assert "script-src 'self';" in csp
    assert "unsafe-inline" not in csp.split("script-src", 1)[1].split(";", 1)[0]
