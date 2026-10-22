"""A minimal 'browser' for Keycloak's login pages in integration tests.

Keycloak sets `Secure; SameSite=None; Version=1` cookies even on http://localhost (browsers treat
localhost as a secure context); Python's cookie jar refuses to send those over http, so cookies
are kept by hand. With Organizations enabled, Keycloak shows identity-first login: a username page,
then a password page; `login` fills whichever fields each form asks for.
"""

import html
import re

import httpx

_FORM = re.compile(r'<form[^>]*action="([^"]+)"')
_INPUT = re.compile(r'<input[^>]*name="([^"]+)"')


class KeycloakBrowser:
    """Follows Keycloak's pages and keeps its cookies; stops at the redirect back to the app."""

    def __init__(self) -> None:
        self._http = httpx.Client(follow_redirects=False, timeout=15)
        self.cookies: dict[str, str] = {}

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        headers = (
            {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}
            if self.cookies
            else {}
        )
        response = self._http.request(method, url, headers=headers, **kwargs)  # type: ignore[arg-type]
        for header in response.headers.get_list("set-cookie"):
            name, _, rest = header.partition("=")
            value = rest.split(";", 1)[0]
            if not value or "Max-Age=0" in header:
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = value
        return response

    def open(self, url: str) -> httpx.Response:
        """GET a Keycloak URL (e.g. the authorization URL the BFF redirected to)."""
        return self._request("GET", url)

    def login(self, authorize_url: str, username: str, password: str) -> httpx.Response:
        """Log in and return the final response: a redirect to the app, or a page (error)."""
        response = self.open(authorize_url)
        for _ in range(4):
            form = _FORM.search(response.text)
            if response.status_code != 200 or form is None:
                break
            fields = set(_INPUT.findall(response.text))
            data = {
                k: v for k, v in (("username", username), ("password", password)) if k in fields
            }
            response = self._request("POST", html.unescape(form.group(1)), data=data)
        return response

    @staticmethod
    def shows_login_form(response: httpx.Response) -> bool:
        """Whether Keycloak asked for credentials (i.e. there was no SSO session)."""
        return response.status_code == 200 and "kc-form-login" in response.text
