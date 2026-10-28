"""The upgrade step giving existing realms the SupportX login theme (tooling/keycloak_theme.py)."""

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from tooling.keycloak_theme import KeycloakUnavailableError, Outcome, Target, run

BASE = "http://keycloak:8080/auth"
RIGHT = "right"  # the fake admin password (test data)


class FakeKeycloak:
    """Keycloak's token and realm endpoints, recording the updates it receives."""

    def __init__(self, realm: dict[str, Any] | None, *, password: str = RIGHT) -> None:
        self.realm = realm
        self.password = password
        self.updates: list[dict[str, Any]] = []
        self.failures_left = 0  # answer 503 this many times first (Keycloak starting)

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.failures_left:
            self.failures_left -= 1
            return httpx.Response(503)
        path = request.url.path.removeprefix("/auth")
        if path == "/realms/master/protocol/openid-connect/token":
            form = dict(x.split("=") for x in request.content.decode().split("&"))
            if form["client_id"] != "admin-cli" or form["password"] != self.password:
                return httpx.Response(401, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "token"})
        assert request.headers["Authorization"] == "Bearer token"
        if path != "/admin/realms/supportx" or self.realm is None:
            return httpx.Response(404)
        if request.method == "PUT":
            body = json.loads(request.content)
            self.updates.append(body)
            self.realm.update(body)
            return httpx.Response(204)
        return httpx.Response(200, json=self.realm)


async def _run(keycloak: FakeKeycloak, password: str = RIGHT, wait: float = 0) -> Any:  # noqa: ANN401 - Result
    return await run(
        Target(BASE, user="admin", password=password),
        wait_seconds=wait,
        transport=httpx.MockTransport(keycloak.handler),
        retry_seconds=0,
    )


async def test_sets_the_theme_on_a_realm_without_one() -> None:
    keycloak = FakeKeycloak({"realm": "supportx", "displayName": "SupportX"})
    result = await _run(keycloak)
    assert (result.outcome, result.theme) == (Outcome.SET, "supportx")
    # Only the login theme is sent: nothing else of the realm is touched.
    assert keycloak.updates == [{"loginTheme": "supportx"}]
    assert (await _run(keycloak)).outcome == Outcome.KEPT  # idempotent: the next deploy keeps it


@pytest.mark.parametrize("chosen", ["keycloak.v2", "acme-corp", "supportx"])
async def test_never_overwrites_a_chosen_theme(chosen: str) -> None:
    keycloak = FakeKeycloak({"realm": "supportx", "loginTheme": chosen})
    result = await _run(keycloak)
    assert (result.outcome, result.theme) == (Outcome.KEPT, chosen)
    assert keycloak.updates == []


async def test_empty_theme_counts_as_none() -> None:
    keycloak = FakeKeycloak({"realm": "supportx", "loginTheme": ""})
    assert (await _run(keycloak)).outcome == Outcome.SET


async def test_missing_realm_and_refused_admin_change_nothing() -> None:
    assert (await _run(FakeKeycloak(None))).outcome == Outcome.NO_REALM
    keycloak = FakeKeycloak({"realm": "supportx"})
    assert (await _run(keycloak, password="replaced")).outcome == Outcome.ADMIN_REFUSED
    assert keycloak.updates == []


async def test_waits_for_keycloak_to_start_then_gives_up() -> None:
    keycloak = FakeKeycloak({"realm": "supportx"})
    keycloak.failures_left = 3
    assert (await _run(keycloak, wait=30)).outcome == Outcome.SET
    down = FakeKeycloak({"realm": "supportx"})
    down.failures_left = 10_000
    with pytest.raises(KeycloakUnavailableError):
        await _run(down, wait=0)


async def test_unreachable_keycloak_is_an_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        message = "connection refused"
        raise httpx.ConnectError(message, request=request)

    with pytest.raises(KeycloakUnavailableError, match="refused"):
        await run(
            Target(BASE, user="admin", password=RIGHT),
            wait_seconds=0,
            transport=httpx.MockTransport(refuse),
            retry_seconds=0,
        )


def test_the_login_template_loads_the_tenant_stylesheet() -> None:
    """WP-017 (REQ-SEC-003): the overridden template keeps its SupportX block after upgrades."""
    from pathlib import Path  # noqa: PLC0415 - only this test reads theme files

    theme = Path(__file__).resolve().parents[2] / "deploy/helm/supportx/files/keycloak/themes"
    template = (theme / "supportx/login/template.ftl").read_text(encoding="utf-8")
    assert "org.attributes.tenant_id??" in template
    assert (
        "${properties.supportxBrandingUrl}/${org.attributes.tenant_id[0]?url('UTF-8')}/login.css"
        in template
    )
    assert "org.alias" not in template  # slugs are guessable: never the key of public URLs
    assert template.count("<#-- /SupportX -->") == 2  # the stylesheet, and the tenant's name
    properties = (theme / "supportx/login/theme.properties").read_text(encoding="utf-8")
    assert "supportxBrandingUrl=${env.SUPPORTX_BRANDING_URL:/api/v1/public/branding}" in properties


def test_bug_08_the_login_page_names_the_tenant() -> None:
    """WP-017-FIX BUG-08 (REQ-SEC-003: logo, colours and name): the organization's name is shown
    under the logo when Keycloak knows the organization, escaped (FreeMarker's HTML output), and
    styled readable in every theme by the same stylesheet as the colours."""
    import re  # noqa: PLC0415 - only these tests read theme files
    from pathlib import Path  # noqa: PLC0415

    from app.modules.organization.domain.branding import DEFAULT_COLOURS  # noqa: PLC0415
    from app.modules.organization.domain.login_css import login_css  # noqa: PLC0415

    theme = Path(__file__).resolve().parents[2] / "deploy/helm/supportx/files/keycloak/themes"
    template = (theme / "supportx/login/template.ftl").read_text(encoding="utf-8")
    header = template[template.index('<header id="kc-header"') : template.index("</header>")]
    block = re.search(r"<#if org\?\? && org\.name\?has_content>(.*?)</#if>", header, re.DOTALL)
    assert block is not None, "the tenant's name is not in the sign-in page header"
    assert '<p id="supportx-org-name" class="supportx-org-name">${org.name}</p>' in block[1]
    assert "?no_esc" not in block[1]  # a tenant's name is text, never markup
    assert template.startswith("<#--")  # keycloak.v2 templates use HTML auto-escaping
    css = login_css(DEFAULT_COLOURS, None)
    assert ".supportx-org-name" in css
    generated = (theme / "supportx/login/resources/css/supportx.css").read_text(encoding="utf-8")
    assert ".supportx-org-name" in generated  # `make brand-assets` ran


# --- the login theme's texts (WP-039 session 2, REQ-SEC-005 AC1 and AC3) ----------------------

LOGIN_THEME = (
    Path(__file__).resolve().parents[2]
    / "deploy/helm/supportx/files/keycloak/themes/supportx/login"
)
# The messages Keycloak shows when a new password breaks the policy SupportX sets.
POLICY_MESSAGES = (
    "invalidPasswordMinLengthMessage",
    "invalidPasswordMinDigitsMessage",
    "invalidPasswordMinLowerCaseCharsMessage",
    "invalidPasswordMinUpperCaseCharsMessage",
    "invalidPasswordMinSpecialCharsMessage",
    "invalidPasswordNotUsernameMessage",
    "invalidPasswordNotEmailMessage",
    "invalidPasswordHistoryMessage",
    "invalidPasswordBlacklistedMessage",
)


def _messages(language: str) -> dict[str, str]:
    path = LOGIN_THEME / "messages" / f"messages_{language}.properties"
    lines = path.read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def test_urdu_has_every_password_rule_message_and_reads_right_to_left() -> None:
    """Keycloak ships Arabic but no Urdu, and does not count Urdu as right to left."""
    urdu = _messages("ur")
    assert [key for key in POLICY_MESSAGES if key not in urdu] == []
    assert "{0}" in urdu["invalidPasswordMinLengthMessage"]  # the length the policy asks for
    template = (LOGIN_THEME / "template.ftl").read_text(encoding="utf-8")
    assert "(locale.rtl || lang == 'ur')?then('rtl','ltr')" in template


def test_a_breached_password_is_refused_with_a_reason_in_every_language() -> None:
    for language in ("en", "ar", "ur"):
        assert _messages(language)["invalidPasswordBlacklistedMessage"], language


def test_a_locked_account_reads_exactly_like_a_wrong_password() -> None:
    """D-104: one text for every failed sign-in; it says when to retry, never what happened."""
    for language in ("en", "ar", "ur"):
        messages = _messages(language)
        texts = {
            messages[key]
            for key in (
                "invalidUserMessage",
                "accountTemporarilyDisabledMessage",
                "accountPermanentlyDisabledMessage",
            )
        }
        assert len(texts) == 1, language
        assert "15" in texts.pop(), language


# Keys of Keycloak 26.8.1's login pages that SupportX shows (keycloak.v2 + base templates: sign-in,
# password, update password, two-step set-up and code, recovery codes, info, error, expired).
SHOWN_PAGE_KEYS = (
    "accountPasswordUpdatedMessage",
    "accountUpdatedMessage",
    "alreadyLoggedIn",
    "auth-recovery-code-header",
    "auth-recovery-code-prompt",
    "authenticatorCode",
    "backToApplication",
    "backToLogin",
    "code-clipboard-label",
    "code-copy-failure",
    "code-copy-label",
    "code-copy-success",
    "codeErrorTitle",
    "codeSuccess",
    "codeSuccessTitle",
    "configureTotpMessage",
    "confirmExecutionOfActions",
    "cookieNotFoundMessage",
    "copyCodeInstruction",
    "doCancel",
    "doClickHere",
    "doForgotPassword",
    "doLogIn",
    "doLogout",
    "doRegister",
    "doSubmit",
    "doSwitchOrganization",
    "doTryAnotherWay",
    "email",
    "emailForgotTitle",
    "emailInstruction",
    "emailInstructionUsername",
    "emailSendErrorMessage",
    "emailSentMessage",
    "errorTitle",
    "expiredActionMessage",
    "expiredActionTokenNoSessionMessage",
    "expiredActionTokenSessionExistsMessage",
    "expiredCodeMessage",
    "identity-provider-login-label",
    "invalidCodeMessage",
    "invalidTotpMessage",
    "loginAccountTitle",
    "loginChooseAuthenticator",
    "loginOtpOneTime",
    "loginTimeout",
    "loginTitleHtml",
    "loginTotpAlgorithm",
    "loginTotpCounter",
    "loginTotpDeviceName",
    "loginTotpDigits",
    "loginTotpInterval",
    "loginTotpManualStep2",
    "loginTotpManualStep3",
    "loginTotpScanBarcode",
    "loginTotpStep1",
    "loginTotpStep2",
    "loginTotpStep3",
    "loginTotpStep3DeviceName",
    "loginTotpTitle",
    "loginTotpType",
    "loginTotpUnableToScan",
    "logoutConfirmHeader",
    "logoutConfirmTitle",
    "logoutOtherSessions",
    "missingPasswordMessage",
    "missingTotpDeviceNameMessage",
    "missingTotpMessage",
    "noAccount",
    "notMatchPasswordMessage",
    "pageExpiredMsg1",
    "pageExpiredMsg2",
    "pageExpiredTitle",
    "password",
    "passwordConfirm",
    "passwordNew",
    "proceedWithAction",
    "recovery-code-config-header",
    "recovery-code-config-warning-message",
    "recovery-code-config-warning-title",
    "recovery-codes-action-cancel",
    "recovery-codes-action-complete",
    "recovery-codes-confirmation-message",
    "recovery-codes-copy",
    "recovery-codes-download",
    "recovery-codes-download-file-date",
    "recovery-codes-download-file-description",
    "recovery-codes-download-file-header",
    "recovery-codes-error-invalid",
    "recovery-codes-label-default",
    "recovery-codes-print",
    "rememberMe",
    "requiredAction.CONFIGURE_RECOVERY_AUTHN_CODES",
    "requiredAction.CONFIGURE_TOTP",
    "requiredAction.UPDATE_PASSWORD",
    "requiredAction.UPDATE_PROFILE",
    "requiredAction.VERIFY_EMAIL",
    "requiredFields",
    "restartLoginTooltip",
    "sessionNotActiveMessage",
    "showPassword",
    "staleCodeMessage",
    "traceIdSupportMessage",
    "updatePasswordMessage",
    "updatePasswordTitle",
    "username",
    "usernameOrEmail",
)


def test_bug_04_urdu_has_every_text_of_the_pages_people_see() -> None:
    """QA WP-039 BUG-04: Keycloak ships no Urdu; English must never show on an Urdu page."""
    urdu = _messages("ur")
    missing = [key for key in SHOWN_PAGE_KEYS if key not in urdu]
    assert missing == [], missing
    untranslated = [key for key in SHOWN_PAGE_KEYS if re.search(r"[A-Za-z]{4,}", urdu[key])]
    assert untranslated == [], untranslated  # translated, not copied


def test_bug_05_the_arabic_update_password_page_asks_to_update_it() -> None:
    """QA WP-039 BUG-05: Keycloak's Arabic titled the form "Password updated"."""
    title = _messages("ar")["updatePasswordTitle"]
    assert title == "تحديث كلمة المرور"
    assert not title.startswith("تم")


def test_bug_02_a_dead_link_says_so_instead_of_the_sign_in_failure_text() -> None:
    """QA WP-039 BUG-02: a withdrawn invitation's link showed "Invalid username or password…"."""
    page = (LOGIN_THEME / "error.ftl").read_text(encoding="utf-8")
    assert 'message.summary == msg("invalidUserMessage")' in page
    assert 'msg("supportxLinkNoLongerValidMessage")' in page
    for language in ("en", "ar", "ur"):
        text = _messages(language)["supportxLinkNoLongerValidMessage"]
        assert text
        assert text != _messages(language)["invalidUserMessage"]
