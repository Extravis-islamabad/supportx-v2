"""The CI tab's rows carry only fields no role rule can withhold (lane C's #644 review).

`ci_linked_port._record` returns `subject` and `status` as stored. That is safe only while ADR-047
never offers them to rules: a rule is saved only for a field in the catalogue
(identity_access/service/field_access.py), and work items' catalogue is `BUILTIN` plus custom
fields. Should a core field ever become rule-able, this fails, and the port must withhold it.
"""

from app.modules.work_items.domain.field_access import BUILTIN, CUSTOM

# What a CiLinkedRecord carries from the record, besides its ID, type and times.
_ROW_FIELDS = frozenset({"display_id", "subject", "status", "status_category"})


def test_no_field_the_ci_tab_shows_can_be_ruled_on_any_type() -> None:
    for record_type, fields in BUILTIN.items():
        ruled = _ROW_FIELDS & frozenset(fields)
        assert not ruled, (
            f"{record_type}: {sorted(ruled)} became rule-able; withhold it in the port"
        )
        assert not any(f.startswith(CUSTOM) for f in _ROW_FIELDS)
