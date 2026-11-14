"""No notification or template variable names a field an admin may restrict (ADR-047 §11).

A notice or a reply template is rendered once for many people; a variable for a restrictable
field would put a value in front of someone a rule hides it from. So the catalogue offers none:
this fails the day one is added, so its author must design per-recipient rendering first.
Reply and resolution templates use the same catalogue (work_items/domain/text_templates.py).
"""

from app.core.modules import discover_modules
from app.modules.work_items.domain.field_access import BUILTIN, CUSTOM
from app.shared.notifications.ports import record_sources

discover_modules()  # every module registers its notification events at import

RESTRICTABLE = {name for fields in BUILTIN.values() for name in fields}


def test_no_variable_names_a_restrictable_field() -> None:
    named = [
        (f"{source.record_type}:{event.code}", variable.name)
        for source in record_sources()
        for event in source.events
        for variable in event.variables
    ] + [
        (f"{source.record_type}:(every event)", variable.name)
        for source in record_sources()
        for variable in source.variables
    ]
    offenders = sorted(
        f"{where}:{name}"
        for where, name in named
        if name.split(".")[-1] in RESTRICTABLE or CUSTOM in name
    )
    assert offenders == [], f"a variable names a restrictable field: {offenders}"


def test_the_catalogue_is_not_empty() -> None:
    """The check looks at something: sources and their events are registered."""
    assert any(source.events for source in record_sources())
