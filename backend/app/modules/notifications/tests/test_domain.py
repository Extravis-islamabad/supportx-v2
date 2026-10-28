"""Notification rules, recipients, preferences and templates without I/O (WP-023)."""

import uuid

import pytest

from app.modules.notifications.domain.rules import (
    Condition,
    ConditionOperator,
    Preferences,
    Rule,
    SuppressedReason,
    held_back,
    recipients,
)
from app.modules.notifications.domain.templates import (
    TemplateProblemError,
    html_body,
    nest,
    render,
    unknown_variables,
)
from app.shared.notifications.ports import EventDefault, NotificationChannel

IN_APP, EMAIL = NotificationChannel.IN_APP, NotificationChannel.EMAIL
A, B, C, D = (uuid.UUID(int=i) for i in range(1, 5))


def test_a_default_rule_needs_no_set_up() -> None:
    rule = Rule.from_default(EventDefault(enabled=True, recipients=("requester",)))
    assert rule.applies({})
    assert rule.channels == (IN_APP, EMAIL)


def test_conditions_limit_the_records() -> None:
    rule = Rule(
        enabled=True,
        recipients=("requester",),
        channels=(IN_APP,),
        conditions=(Condition("priority", ConditionOperator.IN, ("p1", "p2")),),
    )
    assert rule.applies({"priority": "p1"})
    assert not rule.applies({"priority": "p3"})
    assert not rule.applies({})
    off = Rule(enabled=False, recipients=("requester",), channels=(IN_APP,))
    assert not off.applies({"priority": "p1"})
    not_in = Condition("status_category", ConditionOperator.NOT_IN, ("closed",))
    assert not_in.matches({"status_category": "open"})
    assert not not_in.matches({"status_category": "closed"})


def test_one_message_per_person_and_never_the_actor() -> None:
    rule = Rule(
        enabled=True,
        recipients=("assignee", "followers"),
        channels=(IN_APP,),
        user_ids=(C,),
        group_ids=(uuid.UUID(int=9),),
    )
    reached = recipients(
        rule,
        {"assignee": frozenset({A}), "followers": frozenset({A, B, D})},
        {uuid.UUID(int=9): frozenset({B, C})},
        actor_id=D,
    )
    by_user = {r.user_id: r.reasons for r in reached}
    assert by_user == {
        A: ("assignee", "followers"),
        B: ("followers", "group"),
        C: ("user", "group"),
    }
    keep = Rule(enabled=True, recipients=("followers",), channels=(IN_APP,), notify_actor=True)
    assert {r.user_id for r in recipients(keep, {"followers": frozenset({D})}, {}, D)} == {D}


def test_preferences_and_do_not_disturb_never_hold_back_required_or_urgent() -> None:
    prefs = Preferences(off=frozenset({("conversation", EMAIL)}), do_not_disturb=True)
    common = {"required": False, "urgent": False}
    assert held_back(prefs, category="conversation", channel=EMAIL, **common) is (
        SuppressedReason.PREFERENCE
    )
    assert held_back(prefs, category="conversation", channel=IN_APP, **common) is None
    assert held_back(prefs, category="status", channel=EMAIL, **common) is (
        SuppressedReason.DO_NOT_DISTURB
    )
    assert held_back(prefs, category="status", channel=EMAIL, required=False, urgent=True) is None
    assert (
        held_back(prefs, category="conversation", channel=EMAIL, required=True, urgent=False)
        is None
    )


def test_templates_name_unknown_variables_and_allow_objects_of_known_ones() -> None:
    offered = {"record.title", "record.asset.name", "requester.name"}
    source = "{% if record.asset %}{{ record.asset.name }}{% endif %}{{ record.title }}"
    assert unknown_variables(source, offered) == []
    assert unknown_variables("{{ record.secret }} {{ settings }}", offered) == [
        "record.secret",
        "settings",
    ]
    loop = "{% for name in requester.name %}{{ name }}{% endfor %}"
    assert unknown_variables(loop, offered) == []
    with pytest.raises(TemplateProblemError) as broken:
        unknown_variables("{{ record.title ", offered)
    assert broken.value.code == "template_syntax"


def test_rendering_fills_values_and_never_shows_a_code_for_a_missing_one() -> None:
    rendered = render(
        "Hello {{ recipient.name }}\nabout {{ record.title }}",
        "{{ record.title }} by {{ requester.name }}",
        {"recipient.name": "Ana", "record.title": "VPN", "requester.name": None},
    )
    assert rendered.subject == "Hello Ana about VPN"  # one line
    assert rendered.body == "VPN by"
    assert nest({"a.b": 1, "a.c": 2, "d": 3}) == {"a": {"b": 1, "c": 2}, "d": 3}


def test_the_sandbox_reaches_nothing_but_the_variables() -> None:
    attack = "{{ record.title.__class__.__mro__ }}"
    with pytest.raises(Exception, match=r"unsafe|attribute"):
        render(attack, "", {"record.title": "x"})


def test_email_html_is_escaped_paragraphs_with_a_button() -> None:
    html = str(
        html_body(
            "<b>hi</b>\nline two\n\nsecond",
            link="https://x.test/incidents/1",
            link_text="Open INC-1",
            colour="#7b3fe4",
        )
    )
    assert "&lt;b&gt;hi&lt;/b&gt;<br>line two" in html
    assert html.count("<p ") == 3
    assert 'href="https://x.test/incidents/1"' in html
