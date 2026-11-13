"""Person erasure, the pure parts (D-171, ADR-052): the D6b code, states, retries, port registry."""

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access.domain import erasure as rules
from app.modules.identity_access.domain.erasure import ErasureState, Step
from app.modules.identity_access.service import person_data
from app.modules.identity_access.service.person_data import (
    ERASE_BATCH,
    REQUIRED_PORTS,
    ErasureBatch,
    PersonData,
    PortRegistrationError,
    missing_ports,
    register_person_data,
    registered_ports,
    unregister_person_data,
)
from app.modules.identity_access.service.person_data_ports import LANE_B_PORTS
from app.shared.erasure import ERASED_ON_REQUEST, ERASED_ON_REQUEST_LABEL, is_erased_marker
from tests.test_error_labels import label_keys

ID = uuid.UUID("01936b6e-0000-7000-8000-000000000001")


def test_d6b_code_is_four_stable_base32_characters_from_the_id_only() -> None:
    code = rules.erased_code(ID)
    assert len(code) == rules.CODE_LENGTH == 4
    assert set(code) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    assert rules.erased_code(ID) == code  # stable: the same person always shows the same code
    assert rules.erased_code(uuid.UUID(int=ID.int + 1)) != code
    assert rules.erased_name(ID) == f"Erased person {code}"
    assert rules.erased_email(ID) == f"erased-{ID}@invalid"


def test_the_code_spreads_and_hides_the_id() -> None:
    codes = {rules.erased_code(uuid.uuid4()) for _ in range(2000)}
    assert len(codes) > 1990  # 32^4 values: collisions are rare
    # No part of the ID's text shows in the code (it is a hash, not an encoding of the ID).
    for _ in range(200):
        person = uuid.uuid4()
        assert rules.erased_code(person).lower() not in person.hex


@pytest.mark.parametrize(
    ("move", "state", "allowed"),
    [
        ("approve", ErasureState.REQUESTED, True),
        ("approve", ErasureState.APPROVED, False),
        ("approve", ErasureState.EXPIRED, False),
        ("reject", ErasureState.REQUESTED, True),
        ("reject", ErasureState.APPROVED, True),
        ("reject", ErasureState.RUNNING, False),
        ("reject", ErasureState.FAILED, False),
        ("expire", ErasureState.REQUESTED, True),
        ("expire", ErasureState.APPROVED, False),
        ("start", ErasureState.APPROVED, True),
        ("start", ErasureState.RUNNING, True),
        ("start", ErasureState.REQUESTED, False),
        ("start", ErasureState.DONE, False),
        ("start", ErasureState.FAILED, False),
    ],
)
def test_state_transitions(move: str, state: ErasureState, allowed: bool) -> None:
    found = rules.can(move, state)
    assert found.allowed is allowed
    assert found.code == (None if allowed else rules.NOT_PENDING)


def test_open_states_block_a_second_erasure_and_failed_stays_open() -> None:
    assert rules.is_open(ErasureState.FAILED)  # half-erased: nothing new may start
    assert not rules.is_open(ErasureState.DONE)
    assert not rules.is_open(ErasureState.REJECTED)
    assert not rules.is_open(ErasureState.EXPIRED)


def test_steps_are_the_adr_order() -> None:
    assert [step.name for step in Step] == [
        "RECHECK",
        "FREEZE",
        "MAIL",
        "KEYCLOAK",
        "PORTS",
        "PERSON_ROW",
        "AUDIT",
        "EVENTS",
    ]
    assert rules.LAST_STEP == 8


def test_requests_expire_after_seven_days() -> None:
    asked = datetime(2026, 11, 1, 9, tzinfo=UTC)
    assert not rules.is_expired(asked, asked + timedelta(days=7) - timedelta(seconds=1))
    assert rules.is_expired(asked, asked + timedelta(days=7))


def test_retry_backoff_doubles_up_to_an_hour() -> None:
    assert rules.retry_delay(0) == timedelta(0)
    assert rules.retry_delay(1) == timedelta(seconds=30)
    assert rules.retry_delay(2) == timedelta(seconds=60)
    assert rules.retry_delay(40) == timedelta(hours=1)


def test_typed_name_ignores_case_and_spacing() -> None:
    assert rules.same_name("  ahmed   ALI ", "Ahmed Ali")
    assert not rules.same_name("Ahmed", "Ahmed Ali")


# --- the port registry ----------------------------------------------------------------------------


class _Port:
    module: ClassVar[str] = "test_port"
    order: ClassVar[int] = 150
    kinds: ClassVar[frozenset[str]] = frozenset({"test_rows"})

    async def erase_person(
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        del session, person_id, successor_id, keep_files, now, cursor
        return ErasureBatch({})


def test_lane_b_ports_are_registered_in_their_bands_and_required() -> None:
    names = [port.module for port in registered_ports()]
    lane_b = [port.module for port in LANE_B_PORTS]
    assert set(lane_b) <= set(names)
    assert frozenset(lane_b) == REQUIRED_PORTS
    assert missing_ports() == []
    # References first (links, memberships), then owned rows, files last of lane B's.
    ordered = [name for name in names if name in lane_b]
    assert ordered == [
        "action_links",
        "organization",
        "identity_access",
        "list_settings",
        "audit",
        "files",
    ]
    for port in LANE_B_PORTS:
        assert isinstance(port, PersonData)
        assert any(port.order in band for band in person_data.BANDS)


def test_a_port_outside_the_bands_or_twice_is_refused() -> None:
    class Outside(_Port):
        order: ClassVar[int] = 300

    with pytest.raises(PortRegistrationError):
        register_person_data(Outside())
    first = _Port()
    register_person_data(first)
    try:
        register_person_data(first)  # the same object again: fine
        with pytest.raises(PortRegistrationError):
            register_person_data(_Port())
    finally:
        unregister_person_data("test_port")


def test_batches_are_bounded() -> None:
    assert ERASE_BATCH == 500
    assert ErasureBatch({"x": 1}).cursor is None


def test_a_missing_required_port_is_reported() -> None:
    assert missing_ports(REQUIRED_PORTS | {"knowledge"}) == ["knowledge"]


# --- labels (rule d) ------------------------------------------------------------------------------


@pytest.mark.parametrize("locale", ["en", "ar", "ur"])
def test_every_erasure_code_has_a_label(locale: str) -> None:
    keys = label_keys(locale)
    wanted = {f"errors.{code}" for code in rules.PROBLEM_CODES}
    wanted |= {f"errors.field.{code}" for code in rules.FIELD_PROBLEMS}
    wanted |= {f"people_erasure.state.{state.value}" for state in ErasureState}
    wanted |= {f"people_erasure.reason.{reason.value}" for reason in rules.ErasureReason}
    wanted |= {f"people_erasure.step.{step.name.lower()}" for step in Step}
    wanted |= {f"permission.{key}" for key in ("people.erase", "people.export")}
    wanted |= {"permission.audit.manage_holds", "permission_module.people"}
    wanted |= {ERASED_ON_REQUEST_LABEL}
    assert sorted(wanted - keys) == []


def test_the_d2a_marker_is_one_shared_value() -> None:
    from app.modules.identity_access import ERASED_ON_REQUEST as REEXPORTED  # noqa: PLC0415

    assert REEXPORTED == ERASED_ON_REQUEST == "erased_on_request"
    assert is_erased_marker("erased_on_request")
    assert not is_erased_marker("Printer is broken")


def test_every_count_kind_is_labelled_in_every_language() -> None:
    """Lane A's #498 review: the erasure screens show counts, so each kind has a label."""
    import app.modules.identity_access  # noqa: F401, PLC0415 - registers lane B's ports
    from app.modules.identity_access.service.erasure_job import JOB_KINDS  # noqa: PLC0415
    from app.modules.identity_access.service.person_data import (  # noqa: PLC0415
        count_label,
        registered_ports,
    )
    from app.shared.labels import LANGUAGES, missing_labels  # noqa: PLC0415

    kinds = set(JOB_KINDS)
    for port in registered_ports():
        kinds |= set(port.kinds)
    assert missing_labels([count_label(kind) for kind in sorted(kinds)], LANGUAGES) == []


def test_a_module_may_register_one_port_per_band() -> None:
    """Lane A's #498 review: `<module>.<part>` keys, so references run before owned rows."""
    from typing import ClassVar  # noqa: PLC0415

    from app.modules.identity_access.service.person_data import (  # noqa: PLC0415
        ErasureBatch,
        PortRegistrationError,
        register_person_data,
        registered_ports,
        unregister_person_data,
    )

    class _Port:
        order: ClassVar[int] = 150
        module: ClassVar[str] = "example.references"
        kinds: ClassVar[frozenset[str]] = frozenset({"followers_removed"})

        async def erase_person(self, *_a: object, **_k: object) -> ErasureBatch:
            return ErasureBatch({"followers_removed": 0})

    class _Owned(_Port):
        order: ClassVar[int] = 550
        module: ClassVar[str] = "example.owned"

    class _NoKinds(_Port):
        module: ClassVar[str] = "example.bad"
        kinds: ClassVar[frozenset[str]] = frozenset()

    try:
        register_person_data(_Port())
        register_person_data(_Owned())
        keys = [p.module for p in registered_ports()]
        assert keys.index("example.references") < keys.index("example.owned")
        with pytest.raises(PortRegistrationError):
            register_person_data(_NoKinds())
    finally:
        unregister_person_data("example.references")
        unregister_person_data("example.owned")
