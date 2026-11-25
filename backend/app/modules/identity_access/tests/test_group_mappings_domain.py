"""Group mapping rules (WP-057 S5c-1a), with no I/O."""

from app.modules.identity_access.domain.group_mappings import (
    NEVER_VIA_IDP,
    SSO_GROUP_MAPPINGS_READY,
    Held,
    Target,
    overage,
    plan,
    privileged,
)

NET = Target("group", "g-net")
CHG = Target("role", "r-change-manager")


def test_a_new_group_is_gained_and_a_left_one_is_lost() -> None:
    held = {Held(NET, "m1")}
    wanted = {Held(CHG, "m2")}
    done = plan(wanted, held, other_sources=set())
    assert done.add_sources == (Held(CHG, "m2"),)
    assert done.drop_sources == (Held(NET, "m1"),)
    assert done.gain == (CHG,)
    assert done.lose == (NET,)


def test_a_target_another_source_holds_is_kept() -> None:
    done = plan(set(), {Held(NET, "m1")}, other_sources={NET})
    assert done.drop_sources == (Held(NET, "m1"),)
    assert done.lose == ()  # the other connector (or SSO set-up) still gives it


def test_two_mappings_onto_one_target_keep_it_until_both_go() -> None:
    held = {Held(NET, "m1"), Held(NET, "m2")}
    done = plan({Held(NET, "m2")}, held, other_sources=set())
    assert done.drop_sources == (Held(NET, "m1"),)
    assert done.gain == ()
    assert done.lose == ()


def test_nothing_to_do_is_empty() -> None:
    assert plan({Held(NET, "m1")}, {Held(NET, "m1")}, other_sources=set()).empty


def test_privileged_roles_need_the_opt_in() -> None:
    assert privileged("tenant_admin", [])
    for right in NEVER_VIA_IDP:
        assert privileged("custom", ["incidents.view", right]), right
    assert not privileged("change_manager", ["changes.view", "changes.approve"])


def test_an_overlong_or_odd_list_is_an_overage() -> None:
    assert not overage(["a", "b"])
    assert overage(["x"] * 501)
    assert overage(["x" * 257])
    assert overage([""])


def test_sso_mappings_ship_switched_off_until_s5c_1b() -> None:
    assert SSO_GROUP_MAPPINGS_READY is False
