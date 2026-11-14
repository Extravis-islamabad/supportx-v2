"""The mentions report, the pure parts (D-171 a, ADR-052 S1b): terms, matching, the registry."""

from typing import TYPE_CHECKING, cast

import pytest

from app.modules.identity_access.domain import erasure as rules
from app.modules.identity_access.domain.mentions import (
    MentionMatchKind,
    MentionState,
    MentionTerms,
    build_terms,
    count_matches,
    count_matches_html,
    redact,
    redact_html,
)
from app.modules.identity_access.service import person_data
from app.modules.identity_access.service.erasure_mentions import (
    ATTACHMENT_NOTICE_LABEL,
    MAIL_NOTICE_LABEL,
)
from app.modules.identity_access.service.person_data import (
    REQUIRED_MENTION_PORTS,
    PersonMentions,
    PortRegistrationError,
    mention_ports,
    missing_mention_ports,
    register_mentions,
)
from app.modules.identity_access.service.person_mention_ports import LANE_B_MENTION_PORTS
from app.shared.erasure import ERASED_ON_REQUEST
from tests.test_error_labels import label_keys

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

TERMS = build_terms(
    display_name="  Ali   Khan ",
    first_name="Ali",
    last_name="Khan",
    email="Ali.Khan@Example.com",
    phone="+92 300 1234567",
    mobile="12",
)


def test_terms_are_the_full_names_the_address_and_the_numbers() -> None:
    assert TERMS.names == ("Ali Khan",)  # "first last" equals the display name: once
    assert TERMS.emails == ("Ali.Khan@Example.com",)
    assert TERMS.phones == ("923001234567",)  # a 2-digit "mobile" is not a number to search
    custom = build_terms(
        display_name="Dr Ali", first_name="Ali", last_name="Raza", email=None, phone=None,
        mobile=None,
    )  # fmt: skip
    assert set(custom.names) == {"Dr Ali", "Ali Raza"}
    assert build_terms(
        display_name="Al", first_name="Al", last_name=None, email="", phone="", mobile=""
    ).empty()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ask ali   KHAN about it", {MentionMatchKind.NAME: 1}),
        ("Ali Khanum is someone else; so is Ali", {}),
        ("mail ali.khan@example.com, or ALI.KHAN@EXAMPLE.COM.", {MentionMatchKind.EMAIL: 2}),
        ("not x.ali.khan@example.com nor ali.khan@example.com.au", {}),
        ("call 0300-1234567 or (300) 123 4567", {MentionMatchKind.PHONE: 2}),
        ("call +92 300 1234567 today", {MentionMatchKind.PHONE: 1}),
        ("order 1234567 shipped", {}),
        (
            '<p><span data-label="Ali Khan">@Ali Khan</span> 0300 1234567</p>',
            {MentionMatchKind.NAME: 2, MentionMatchKind.PHONE: 1},
        ),
        (None, {}),
    ],
)
def test_matching(text: str | None, expected: dict[MentionMatchKind, int]) -> None:
    assert count_matches(text, TERMS) == expected


def test_redaction_replaces_only_one_kind() -> None:
    text = "Ali Khan (ali.khan@example.com, 0300-1234567) and ali khan again"
    named, count = redact(text, TERMS, MentionMatchKind.NAME, ERASED_ON_REQUEST)
    assert count == 2
    assert named == (
        "erased_on_request (ali.khan@example.com, 0300-1234567) and erased_on_request again"
    )
    mailed, _ = redact(named, TERMS, MentionMatchKind.EMAIL, ERASED_ON_REQUEST)
    assert "example.com" not in mailed
    assert "0300-1234567" in mailed
    assert redact("nothing here", TERMS, MentionMatchKind.PHONE, ERASED_ON_REQUEST) == (
        "nothing here",
        0,
    )
    assert count_matches(mailed, MentionTerms()) == {}


def test_every_required_mentions_port_is_registered() -> None:
    """Every module the report needs has its port since #516: an erasure can be approved."""
    import app.modules.announcements  # noqa: PLC0415 - registers lane C's port
    import app.modules.assets  # noqa: PLC0415 - registers the assets port
    import app.modules.identity_access  # noqa: PLC0415 - registers lane B's ports
    import app.modules.integrations  # noqa: PLC0415 - registers lane A's port
    import app.modules.knowledge  # noqa: PLC0415 - registers lane C's port
    import app.modules.work_items  # noqa: F401, PLC0415 - registers lane A's port

    registered = {port.module for port in mention_ports()}
    assert {
        "work_items",  # one key: a mention search has no band (lane A's #506 review)
        "integrations",
        "knowledge",
        "announcements",
    } <= REQUIRED_MENTION_PORTS
    assert missing_mention_ports(registered) == []
    for port in LANE_B_MENTION_PORTS:
        assert isinstance(port, PersonMentions)


def test_a_second_mentions_port_for_a_key_is_refused() -> None:
    class Bad:
        module = "Not A Key"

    with pytest.raises(PortRegistrationError):
        register_mentions(Bad())  # type: ignore[arg-type]  # deliberately not a port
    files = person_data.mention_port("files")
    assert files is not None
    register_mentions(files)  # the same object again: fine
    with pytest.raises(PortRegistrationError):
        register_mentions(type(files)())


@pytest.mark.parametrize("locale", ["en", "ar", "ur"])
def test_every_mentions_code_has_a_label(locale: str) -> None:
    keys = label_keys(locale)
    wanted = {f"people_erasure.match_kind.{kind.value}" for kind in MentionMatchKind}
    wanted |= {f"people_erasure.mention_state.{state.value}" for state in MentionState}
    wanted |= {ATTACHMENT_NOTICE_LABEL, MAIL_NOTICE_LABEL}
    wanted |= {
        f"errors.{code}"
        for code in (rules.REPORT_NOT_REVIEWED, rules.MENTION_NOT_FOUND, rules.MENTION_PORT_MISSING)
    }
    wanted |= {
        f"audit.action.person.{action}"
        for action in (
            "erasure_report_reviewed",
            "erasure_mention_viewed",
            "erasure_mention_redacted",
        )
    }
    assert sorted(wanted - keys) == []


def test_rich_text_matches_between_tags_only() -> None:
    """A name in an attribute is neither counted nor rewritten (lane A's #506 review)."""
    terms = MentionTerms(names=("Ada Lovelace",), emails=("ada@example.com",))
    html = (
        '<p>Ask <a href="mailto:ada@example.com" title="Ada Lovelace">Ada Lovelace</a>'
        ' or ada@example.com</p><img alt="Ada Lovelace > ok">'
    )
    assert count_matches_html(html, terms) == {
        MentionMatchKind.NAME: 1,
        MentionMatchKind.EMAIL: 1,
    }
    redacted, replaced = redact_html(html, terms, MentionMatchKind.NAME, "erased_on_request")
    assert replaced == 1
    assert redacted == html.replace(">Ada Lovelace</a>", ">erased_on_request</a>")
    assert count_matches_html(None, terms) == {}


async def test_a_field_role_rules_withhold_is_never_shown_or_redacted() -> None:
    """The registry's ADR-047 backstop: hidden or masked → no passage, whatever the port says."""
    import uuid  # noqa: PLC0415 - this test only
    from types import MappingProxyType  # noqa: PLC0415 - this test only

    from app.modules.identity_access.domain.field_access import compile_access  # noqa: PLC0415
    from app.modules.identity_access.domain.policy import Subject  # noqa: PLC0415
    from app.modules.identity_access.service import erasure_mentions  # noqa: PLC0415

    class Open:
        module = "probe"

        async def passage(self, session: object, subject: object, mention: object) -> str:
            del session, subject, mention
            return "the text"

    def subject(mode: str | None) -> Subject:
        rules = [] if mode is None else [("incident", "custom.salary", mode)]
        return Subject(
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            role_keys=frozenset({"technician"}),
            is_tenant_admin=False,
            grants=MappingProxyType({}),
            field_access=compile_access(1, rules),
        )

    mention = person_data.Mention(
        "incident", uuid.uuid4(), "custom.salary", MentionMatchKind.NAME, 1
    )
    readable = erasure_mentions._readable  # noqa: SLF001 - the one check under test
    port = cast("person_data.PersonMentions", Open())
    session = cast("AsyncSession", None)  # the probe port needs none
    assert await readable(session, subject(None), port, mention) == "the text"
    for mode in ("hidden", "masked"):
        assert await readable(session, subject(mode), port, mention) is None
    assert await readable(session, subject("read_only"), port, mention) == "the text"


def test_0164s_redactable_states_are_the_domain_rule() -> None:
    """history_redact_field's fixed state list matches rules.can("redact") (lane C, #506)."""
    import importlib  # noqa: PLC0415 - this test only
    import re  # noqa: PLC0415 - this test only

    from app.modules.identity_access.domain.erasure import ErasureState  # noqa: PLC0415

    migration = importlib.import_module("migrations.versions.0164_person_erasure_mentions")
    fixed = set(re.findall(r"'([a-z_]+)'", migration._REDACTABLE))  # noqa: SLF001 - the constant
    allowed = {s.value for s in ErasureState if rules.can("redact", s).allowed}
    assert fixed == allowed


def test_a_short_one_word_display_name_is_skipped_but_the_full_name_is_searched() -> None:
    """The coordinator's rule (2026-11-14): full first + last always; one word from 4 letters."""
    short = build_terms(
        display_name="Ali",
        first_name="Ali",
        last_name="Raza",
        email=None,
        phone=None,
        mobile=None,
    )
    assert short.names == ("Ali Raza",)
    assert short.short_name_skipped is True
    arabic = build_terms(
        display_name="علي",
        first_name="علي",
        last_name="رضا",
        email=None,
        phone=None,
        mobile=None,
    )  # three letters (six bytes): counted by letter
    assert arabic.names == ("علي رضا",)
    assert arabic.short_name_skipped is True
    long_enough = build_terms(
        display_name="Sara", first_name=None, last_name=None, email=None, phone=None, mobile=None
    )
    assert long_enough.names == ("Sara",)
    assert long_enough.short_name_skipped is False
    several = build_terms(
        display_name="Al Bo", first_name=None, last_name=None, email=None, phone=None, mobile=None
    )
    assert several.names == ("Al Bo",)  # several words: always searched
