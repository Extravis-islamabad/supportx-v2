"""The mail service's rules, pure (domain/message.py, domain/layout.py)."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest

from app.shared.mail.domain.layout import wrap_html
from app.shared.mail.domain.message import (
    MAX_ATTACHMENT_BYTES,
    Attachment,
    MailRefused,
    OutgoingMail,
    build_mime,
    check,
)

MAIL = OutgoingMail(kind="report", to=("pat@acme.test",), subject="Weekly report", text="Hi")


def _mime(mail: OutgoingMail) -> str:
    return build_mime(
        mail,
        from_address="support@acme.test",
        from_name="Acme Service Desk",
        message_id_domain="acme.test",
        sent_at=datetime(2026, 10, 27, tzinfo=UTC),
    ).as_string()


def test_the_sender_is_the_installations_or_the_tenants_name_never_a_persons_address() -> None:
    """REQ-SEC-019 AC1: no field exists for a person's own address."""
    raw = _mime(replace(MAIL, sender_name="Acme IT", reply_to="help@acme.test"))
    assert "From: Acme IT <support@acme.test>" in raw
    assert "Reply-To: help@acme.test" in raw
    assert "Auto-Submitted: auto-generated" in raw
    assert "Content-Language: en" in raw


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"subject": "Hi\r\nBcc: x@evil.test"}, "mail_subject_invalid"),  # header injection
        ({"sender_name": "A\nB"}, "mail_sender_invalid"),
        ({"to": ("not an address",)}, "mail_address_invalid"),
        ({"to": ()}, "mail_recipients"),
        ({"reply_to": "x@y"}, "mail_address_invalid"),
        ({"language": "fr"}, "mail_language_invalid"),
        ({"kind": "Bad Kind"}, "mail_kind_invalid"),
    ],
)
def test_unsafe_or_malformed_messages_are_refused(change: dict[str, object], code: str) -> None:
    with pytest.raises(MailRefused) as refused:
        check(replace(MAIL, **change))  # type: ignore[arg-type]  # the test varies one field
    assert refused.value.code == code


def test_attachments_are_typed_named_and_at_most_10_mb_in_total() -> None:
    csv = Attachment("report.csv", "text/csv", b"a,b\n1,2\n")
    raw = _mime(replace(MAIL, attachments=(csv,)))
    assert 'filename="report.csv"' in raw
    big = Attachment("big.pdf", "application/pdf", b"x" * (MAX_ATTACHMENT_BYTES + 1))
    for attachment, code in (
        (big, "mail_attachments_too_large"),
        (Attachment("x.exe", "application/x-msdownload", b"MZ"), "mail_attachment_type"),
        (Attachment("../x.csv", "text/csv", b""), "mail_attachment_name"),
    ):
        with pytest.raises(MailRefused) as refused:
            check(replace(MAIL, attachments=(attachment,)))
        assert refused.value.code == code


@dataclass
class Brand:
    product_name: str = "Acme <Desk>"
    primary_colour: str = "#0b5394"
    gradient: tuple[str, str] = ("#0b5394", "#123456")
    logo_url: str | None = "https://acme.test/logo.png?v=2"
    portal_url: str = "https://acme.test/portal/"


def test_the_layout_carries_the_brand_escaped_and_reads_right_to_left_in_arabic() -> None:
    html = wrap_html("<p>مرحبا</p>", brand=Brand(), language="ar", title="<t>")
    assert '<html lang="ar" dir="rtl">' in html
    assert 'alt="Acme &lt;Desk&gt;"' in html  # names are escaped
    assert "<title>&lt;t&gt;</title>" in html
    assert "<p>مرحبا</p>" in html  # the caller's content kept as markup
    assert "linear-gradient(90deg,#0b5394,#123456)" in html
    english = wrap_html("<p>Hi</p>", brand=Brand(logo_url=None), language="en", title="T")
    assert 'dir="ltr"' in english
    assert ">Acme &lt;Desk&gt;</span>" in english  # no logo: the name
