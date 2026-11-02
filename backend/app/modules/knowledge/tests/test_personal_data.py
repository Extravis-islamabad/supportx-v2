from app.modules.knowledge.domain.personal_data import Finding, find_personal_data, plain_text


def kinds(title: str, body: str = "") -> set[tuple[str, str]]:
    return {(f.field, f.kind) for f in find_personal_data(title, body)}


def test_ordinary_steps_find_nothing() -> None:
    body = "<p>Restart the router, wait 30 seconds, then open https://portal/vpn on port 8443.</p>"
    assert find_personal_data("VPN reset", body) == []
    assert (
        find_personal_data("إعادة ضبط الشبكة", "<p>أعد تشغيل الجهاز ثم انتظر ٣٠ ثانية.</p>") == []
    )


def test_email_phone_account_and_password_are_found_by_field() -> None:
    body = (
        "<p>Called Sara on +966 50 123 4567, wrote to sara.k@example.com.</p>"
        "<p>Refund to SA03 8000 0000 6080 1016 7519. Temporary password: Winter2026</p>"
    )
    assert kinds("Mail for sara.k@example.com", body) == {
        ("title", "email"),
        ("body", "email"),
        ("body", "phone"),
        ("body", "account_number"),
        ("body", "password"),
    }


def test_arabic_text_and_arabic_indic_digits() -> None:
    body = "<p>اتصل على ٠٥٠١٢٣٤٥٦٧ وكلمة المرور: ١٢٣٤</p>"
    assert kinds("", body) == {("body", "phone"), ("body", "password")}
    assert Finding("body", "phone") in find_personal_data("", "<p>۰۵۰۱۲۳۴۵۶۷</p>")


def test_short_numbers_are_not_phones() -> None:
    assert kinds("", "<p>Error 404 on port 8443, ticket 1234-56.</p>") == set()


def test_plain_text_drops_tags_and_reads_entities() -> None:
    assert plain_text("<p>a&nbsp;&amp;&nbsp;b</p><p>c</p>").split() == ["a", "&", "b", "c"]
