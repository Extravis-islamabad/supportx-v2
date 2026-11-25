"""Group mapping rules (WP-057 S5c-1a, S5c-1b), with no I/O."""

import pytest

from app.modules.identity_access.domain import group_mappings as gm
from app.modules.identity_access.domain.group_mappings import (
    NEVER_VIA_IDP,
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


# --- a sign-in's groups (WP-057 S5c-1b) ------------------------------------------------------

NAMES = gm.GroupAttributeNames(
    groups="sx_groups_a", seen="sx_groups_seen_a", overage="sx_groups_overage_a",
    hasgroups="sx_groups_hasgroups_a",
)  # fmt: skip


def test_a_fresh_list_is_followed_and_an_absent_one_means_none() -> None:
    sent = {"sx_groups_seen_a": ["1"], "sx_groups_a": ["g1", "g2"]}
    assert gm.judge_sign_in_groups(sent, NAMES) == gm.SignInGroups(frozenset({"g1", "g2"}))
    # G2: fresh (seen) and no overage, so an absent list is "in no group now".
    assert gm.judge_sign_in_groups({"sx_groups_seen_a": ["1"]}, NAMES) == gm.SignInGroups(
        frozenset()
    )


@pytest.mark.parametrize(
    "values",
    [
        {"sx_groups_a": ["g1"]},  # not seen: a concurrent sign-in took them, or none ran
        {"sx_groups_seen_a": ["1"], "sx_groups_overage_a": ["src1"], "sx_groups_a": ["g1"]},
        {"sx_groups_seen_a": ["1"], "sx_groups_hasgroups_a": ["true"]},
        {"sx_groups_seen_a": ["1"], "sx_groups_a": ["g"] * (gm.MAX_GROUPS + 1)},
        {"sx_groups_seen_a": ["1"], "sx_groups_a": ["x" * (gm.MAX_GROUP_ID + 1)]},
        {"sx_groups_seen_a": ["1"], "sx_groups_a": [""]},
    ],
)
def test_anything_not_proven_complete_changes_nothing(values: dict[str, list[str]]) -> None:
    judged = gm.judge_sign_in_groups(values, NAMES)
    assert (judged.groups, judged.reason) == (None, gm.IDP_GROUPS_UNVERIFIED)
