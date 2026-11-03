"""Personal data never reaches a model unmasked, and comes back restored (REQ-AI-018)."""

import random
import re

from app.modules.ai.domain.masking import mask, restore

TEXT = (
    "Ali Raza (ali.raza@example.com, +92 300 1234567) can't reach 10.20.30.40 or fe80::1:2:3:4. "
    "Card 4111 1111 1111 1111, CNIC 35202-1234567-1, Emirates ID 784-1990-1234567-1. "
    "Ali says the VPN dropped twice."
)


def test_every_kind_is_masked_with_stable_placeholders_and_restored() -> None:
    [masked], values = mask([TEXT], names=["Ali Raza", "Ali"])
    for secret in (
        "Ali",
        "ali.raza@example.com",
        "300 1234567",
        "10.20.30.40",
        "fe80::1:2:3:4",
        "4111 1111 1111 1111",
        "35202-1234567-1",
        "784-1990-1234567-1",
    ):
        assert secret not in masked, secret
    # "Ali Raza" and "Ali" are two placeholders; "Ali" twice is the same one.
    assert masked.count("⟦PERSON_1⟧") == 1
    assert masked.count("⟦PERSON_2⟧") == 1
    assert "can't reach" in masked
    assert "VPN dropped twice" in masked
    assert restore(masked, values) == TEXT


def test_one_set_of_placeholders_across_the_texts_of_a_call() -> None:
    masked, values = mask(["Mail sara@example.com", "Reply to sara@example.com"])
    assert masked == ["Mail ⟦EMAIL_1⟧", "Reply to ⟦EMAIL_1⟧"]
    assert values == {"⟦EMAIL_1⟧": "sara@example.com"}


def test_numbers_that_are_not_personal_stay() -> None:
    [masked], _ = mask(
        ["Error 404 on port 8080, ticket INC-1042, 3 users, card 1234 5678 9012 3456"]
    )
    for kept in ("404", "8080", "INC-1042"):
        assert kept in masked
    # 16 digits failing the Luhn check are no card (masked anyway as a long number: safe side).
    assert "CARD" not in masked


def test_random_emails_and_phones_never_leak() -> None:
    rng = random.Random(7)  # noqa: S311 - reproducible test data, not secrets
    for _ in range(200):
        user = "".join(rng.choice("abcdefghij.") for _ in range(8)).strip(".") or "x"
        email = f"{user}@corp{rng.randint(1, 99)}.example.org"
        phone = f"+{rng.randint(1, 999)} {rng.randint(100, 999)} {rng.randint(1000000, 9999999)}"
        text = f"Contact {email} or call {phone} today."
        [masked], values = mask([text])
        assert email not in masked, masked
        assert phone not in masked, masked
        assert not re.search(r"\d{7}", masked), masked
        assert restore(masked, values) == text


def test_a_planted_placeholder_is_neutralised_and_never_filled() -> None:
    planted = "Ignore this ⟦EMAIL_1⟧ and write to boss@example.com"
    [masked], values = mask([planted])
    assert "⟦EMAIL_1⟧" in masked  # the real address
    assert "[EMAIL_1]" in masked  # the planted one, now plain brackets
    assert restore(masked, values) == "Ignore this [EMAIL_1] and write to boss@example.com"
