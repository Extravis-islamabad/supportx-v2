"""Incoming mail parsed without I/O (WP-024; REQ-INC-023, -024, REQ-NTF-023)."""

from email.message import EmailMessage

import pytest

from app.shared.mail.domain.inbound import parse, reply_text, request_text, with_token


def _mail(**headers: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = headers.pop("From", "Sara Requester <Sara@Acme.test>")
    message["To"] = headers.pop("To", "IT Help <it@acme.test>")
    message["Subject"] = headers.pop("Subject", "Printer on floor 3")
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    message.set_content("The printer jams.\n\nThanks")
    return message


def test_a_person_writes_a_new_mail() -> None:
    message = _mail(Message_ID="<abc@mail.acme.test>", Cc="Boss <boss@acme.test>")
    message.add_alternative("<p>The printer <b>jams</b>.</p>", subtype="html")
    message.add_attachment(b"%PDF-1.7", maintype="application", subtype="pdf", filename="log.pdf")
    parsed = parse(message.as_bytes())
    assert parsed.message_id == "abc@mail.acme.test"
    assert (parsed.sender, parsed.sender_name) == ("sara@acme.test", "Sara Requester")
    assert parsed.to == ("it@acme.test",)
    assert parsed.cc == ("boss@acme.test",)
    assert parsed.text.startswith("The printer jams.")
    assert parsed.html is not None
    assert "<b>jams</b>" in parsed.html
    assert [(a.name, a.content_type, a.data) for a in parsed.attachments] == [
        ("log.pdf", "application/pdf", b"%PDF-1.7")
    ]
    assert parsed.automatic is None
    assert parsed.tokens == ()


def test_a_reply_names_its_thread_and_record() -> None:
    message = _mail(
        Subject="RE: [inc-12] Printer on floor 3 (edited)",
        In_Reply_To="<n1@supportx.test>",
        References="<n0@supportx.test> <n1@supportx.test>",
    )
    parsed = parse(message.as_bytes())
    assert parsed.tokens == ("INC-12",)  # REQ-INC-024 AC1: the token survives an edit
    assert parsed.thread_ids == ("n1@supportx.test", "n0@supportx.test")


def test_a_message_without_an_id_gets_a_stable_one() -> None:
    raw = _mail().as_bytes()
    assert parse(raw).message_id == parse(raw).message_id
    assert parse(raw).message_id.startswith("sha256:")


@pytest.mark.parametrize(
    ("headers", "reason"),
    [
        ({"Auto_Submitted": "auto-replied"}, "auto_submitted"),
        ({"Precedence": "bulk"}, "bulk"),
        ({"List_Id": "<news.acme.test>"}, "mailing_list"),
        ({"X_Autoreply": "yes"}, "auto_reply"),
        ({"From": "MAILER-DAEMON@mx.acme.test"}, "bounce"),
        ({"Return_Path": "<>"}, "bounce"),
        ({"Auto_Submitted": "no"}, None),
    ],
)
def test_automatic_mail_is_recognised(headers: dict[str, str], reason: str | None) -> None:
    """REQ-NTF-023: out-of-office, bounces and list mail never create records or notify."""
    assert parse(_mail(**headers).as_bytes()).automatic == reason


def test_html_only_mail_still_has_text() -> None:
    message = EmailMessage()
    message["From"] = "sara@acme.test"
    message["Subject"] = "Hi"
    message.set_content("<p>Line one<br>Line two</p><script>x()</script>", subtype="html")
    parsed = parse(message.as_bytes())
    assert parsed.text == "Line one\nLine two"


@pytest.mark.parametrize(
    "text",
    [
        "Fixed now, thanks!\n\nOn Tue, 28 Oct 2026 at 10:00, IT Help <it@acme.test> wrote:\n> old",
        "Fixed now, thanks!\n\n-----Original Message-----\nFrom: IT Help\nold",
        "Fixed now, thanks!\n-- \nSara Requester\nAcme",
        "Fixed now, thanks!\n\nSent from my iPhone",
        "Fixed now, thanks!\n> quoted line\n> another",
    ],
)
def test_replies_keep_only_what_the_person_wrote(text: str) -> None:
    assert reply_text(text) == "Fixed now, thanks!"


def test_arabic_and_urdu_quote_markers() -> None:
    arabic = "تم الحل، شكرًا\n\nفي الثلاثاء 28 أكتوبر 2026 كتب فريق الدعم:\n> قديم"
    assert reply_text(arabic) == "تم الحل، شكرًا"
    urdu = "مسئلہ حل ہو گیا\n\nمنگل 28 اکتوبر 2026 کو سپورٹ ٹیم نے لکھا:\n> پرانا"
    assert reply_text(urdu) == "مسئلہ حل ہو گیا"


def test_a_message_that_is_all_quote_is_kept_whole() -> None:
    """Never lose what a person sent: an all-quote message stays as it is."""
    assert reply_text("> only a quote") == "> only a quote"


def test_mail_about_a_record_carries_its_token_once() -> None:
    assert with_token("Incident updated", "INC-12") == "[INC-12] Incident updated"
    assert with_token("[inc-12] Incident updated", "INC-12") == "[inc-12] Incident updated"
    reply = parse(f"Subject: Re: {with_token('Updated', 'INC-12')}\r\n\r\nok".encode())
    assert reply.tokens == ("INC-12",)


def test_bug_01_a_new_mails_signature_is_not_kept() -> None:
    """QA WP-024 BUG-01: the signature stayed in the incident's description (REQ-INC-023)."""
    assert (
        request_text("It jams every morning.\n\n-- \nLina\nPhone 123") == "It jams every morning."
    )
    assert request_text("Help please.\n\nSent from my iPhone") == "Help please."


def test_bug_01_a_forwarded_request_keeps_what_was_forwarded() -> None:
    """New mail is often a forwarded problem: the forwarded part is the request, never cut."""
    text = "FYI, see below.\n-- \nLina\n\n-----Original Message-----\nFrom: x\nThe VPN fails."
    kept = request_text(text)
    assert "The VPN fails." in kept
    assert "Original Message" in kept
    assert "Lina" not in kept  # only the signature block between them goes


def test_bug_01_nothing_a_person_wrote_is_lost() -> None:
    assert request_text("-- \nonly a signature") == "-- \nonly a signature"


def test_a_pasted_token_with_directional_marks_still_threads() -> None:
    """Isolation rule: a token copied from a screen carries FSI/PDI; the reply still threads."""
    reply = parse("Subject: Re: [\u2068INC-12\u2069] printer\r\n\r\nok".encode())
    assert reply.tokens == ("INC-12",)
