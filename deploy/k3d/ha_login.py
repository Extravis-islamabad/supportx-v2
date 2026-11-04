# ruff: noqa: INP001 - a standalone script the HA smoke runs, not a package
"""Sign in through the BFF as a dev user, for the HA smoke (WP-014b); writes the Cookie header.

The k3d cluster serves http://supportx.localhost. The BFF and Keycloak mark their cookies
Secure, which curl (and Python's cookie jar) won't keep over http://, although browsers treat
*.localhost as secure. So this follows the redirects itself and keeps every cookie it is given.

    uv run --project backend python deploy/k3d/ha_login.py <public url> <user> <out file>

The password comes from HA_LOGIN_PASSWORD. The Cookie header goes to <out file> (mode 600);
nothing secret is printed. Exit 0 once /api/v1/auth/me answers 200 with those cookies.
"""

import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import httpx

FORM = re.compile(r'<form[^>]*id="kc-form-login"[^>]*>', re.IGNORECASE)
ACTION = re.compile(r'action="([^"]+)"')
MAX_HOPS = 20


def _keep(cookies: dict[str, str], response: httpx.Response) -> None:
    for header in response.headers.get_list("set-cookie"):
        name, _, rest = header.partition("=")
        value = rest.split(";", 1)[0]
        if value in ("", '""'):
            cookies.pop(name.strip(), None)  # an expired or cleared cookie
        else:
            cookies[name.strip()] = value


def _header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def _follow(
    client: httpx.Client, cookies: dict[str, str], response: httpx.Response
) -> httpx.Response:
    for _ in range(MAX_HOPS):
        _keep(cookies, response)
        location = response.headers.get("location")
        if response.status_code not in (301, 302, 303, 307) or not location:
            return response
        response = client.get(
            urljoin(str(response.url), location), headers={"Cookie": _header(cookies)}
        )
    msg = "too many redirects"
    raise RuntimeError(msg)


def main(public_url: str, user: str, out: Path) -> int:
    """Sign in, check /auth/me, and write the Cookie header to `out`; the exit status."""
    password = os.environ["HA_LOGIN_PASSWORD"]
    cookies: dict[str, str] = {}
    with httpx.Client(follow_redirects=False, timeout=30) as client:
        start = client.get(f"{public_url}/api/v1/auth/login?app=console&returnTo=/")
        page = _follow(client, cookies, start)
        form = FORM.search(page.text)
        action = ACTION.search(form.group(0)) if form else None
        if action is None:
            sys.stdout.write(f"no Keycloak login form (status {page.status_code})\n")
            return 1
        posted = client.post(
            action.group(1).replace("&amp;", "&"),
            data={"username": user, "password": password},
            headers={"Cookie": _header(cookies)},
        )
        ended = _follow(client, cookies, posted)
        me = client.get(
            f"{public_url}/api/v1/auth/me",
            headers={"Cookie": _header(cookies), "X-SupportX-Client": "console"},
        )
    if me.status_code != 200:  # noqa: PLR2004 - HTTP OK
        where = str(ended.url).split("?", 1)[0]
        sys.stdout.write(
            f"not signed in: the flow ended at {ended.status_code} {where}; "
            f"/auth/me {me.status_code}\ncookies held: {' '.join(sorted(cookies))}\n"
        )
        return 1
    out.write_text(_header(cookies))
    out.chmod(0o600)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], Path(sys.argv[3])))
