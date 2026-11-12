"""Reply and resolution template text (REQ-INC-041, -042), without I/O."""

from app.modules.work_items.domain.text_templates import (
    fill,
    pick_language,
    unknown_variables,
    variables_in,
)

OFFERED = ["record.display_id", "record.title", "requester.name"]


def test_ac1_variables_are_filled_with_the_record_s_values_as_escaped_text() -> None:
    text = "<p>Hello {{ requester.name }}, about {{record.display_id}}: {{ record.title }}</p>"
    filled = fill(
        text,
        {"requester.name": "Sara", "record.display_id": "INC-7", "record.title": "<b>VPN</b>"},
        "not set",
    )
    assert filled == "<p>Hello Sara, about INC-7: &lt;b&gt;VPN&lt;/b&gt;</p>"


def test_ac3_an_empty_variable_reads_as_the_placeholder_never_its_name() -> None:
    filled = fill("<p>{{ requester.name }}</p>", {"requester.name": None}, "not set")
    assert filled == "<p>not set</p>"
    assert "requester.name" not in filled


def test_names_the_catalogue_does_not_offer_are_found_before_saving() -> None:
    text = "{{ record.title }} {{ record.secret }} {{ record.title }}"
    assert variables_in(text) == ["record.title", "record.secret"]
    assert unknown_variables(text, OFFERED) == ["record.secret"]


def test_ac2_the_requester_s_language_comes_first_then_the_tenant_s_then_any() -> None:
    bodies = {"en": "<p>Hi</p>", "ar": "<p>مرحبًا</p>"}
    assert pick_language(bodies, ["ar", "en"]) == "ar"
    assert pick_language(bodies, ["ur", "en"]) == "en"
    assert pick_language({"ar": "<p>x</p>"}, ["ur", "en"]) == "ar"
    assert pick_language({}, ["en"]) is None
