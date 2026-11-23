"""A template's form layout (REQ-INC-036), without I/O."""

from app.modules.work_items.domain.form_layout import (
    LabelPosition,
    LayoutAudience,
    arrange,
    layout_problems,
)

FIELDS = ["subject", "requester_id", "category_id", "site_id", "description", "custom.cost"]
TECH = {
    "label_position": "start",
    "sections": [
        {"id": "who", "names": {"en": "Who", "ar": "من"}, "fields": ["requester_id", "subject"]},
        {
            "id": "where",
            "columns": 2,
            "collapsible": True,
            "collapsed": True,
            "fields": ["site_id", "category_id"],
        },
    ],
}


def test_ac1_fields_land_in_their_sections_and_unplaced_ones_go_last() -> None:
    laid = arrange({"technician": TECH, "requester": None}, LayoutAudience.TECHNICIAN, FIELDS)
    assert laid.label_position is LabelPosition.START
    assert [s.id for s in laid.sections] == ["who", "where"]
    assert list(laid.sections[0].fields) == ["requester_id", "subject"]
    # Not placed by the layout (a new custom field too): end of the last section, usual order.
    assert list(laid.sections[1].fields) == ["site_id", "category_id", "description", "custom.cost"]
    assert (laid.sections[1].columns, laid.sections[1].collapsed) == (2, True)


def test_requester_layout_falls_back_and_hidden_fields_are_left_out() -> None:
    portal = ["subject", "requester_id", "description"]  # what a requester may see
    laid = arrange({"technician": TECH, "requester": None}, LayoutAudience.REQUESTER, portal)
    assert [list(s.fields) for s in laid.sections] == [["requester_id", "subject"], ["description"]]
    own = {"sections": [{"id": "only", "fields": ["description", "subject"]}]}
    laid = arrange({"technician": TECH, "requester": own}, LayoutAudience.REQUESTER, portal)
    assert [list(s.fields) for s in laid.sections] == [["description", "subject", "requester_id"]]
    assert laid.label_position is LabelPosition.TOP


def test_no_layout_is_one_plain_section() -> None:
    laid = arrange(None, LayoutAudience.TECHNICIAN, FIELDS)
    assert [list(s.fields) for s in laid.sections] == [FIELDS]


def test_problems_name_each_part() -> None:
    assert layout_problems({"technician": TECH, "requester": None}, FIELDS) == []
    assert layout_problems(None, FIELDS) == []
    assert layout_problems({"requester": None}, FIELDS) == [("layout.technician", "required")]
    bad = {
        "technician": {
            "label_position": "below",
            "sections": [
                {"id": "a", "columns": 3, "collapsed": True, "fields": ["nope", "subject"]},
                {"id": "a", "names": {"fr": "x"}, "fields": ["subject"]},
            ],
        }
    }
    assert layout_problems(bad, FIELDS) == [
        ("layout.technician.label_position", "invalid_choice"),
        ("layout.technician.sections.0.columns", "invalid_choice"),
        ("layout.technician.sections.0.collapsed", "needs_collapsible"),
        ("layout.technician.sections.0.fields.0", "not_a_form_field"),
        ("layout.technician.sections.1.id", "duplicate_value"),
        ("layout.technician.sections.1.names", "invalid_value"),
        ("layout.technician.sections.1.fields.0", "duplicate_value"),
    ]
    many = {"technician": {"sections": [{"id": f"s{i}", "fields": []} for i in range(21)]}}
    assert layout_problems(many, FIELDS) == [("layout.technician.sections", "too_many_values")]
