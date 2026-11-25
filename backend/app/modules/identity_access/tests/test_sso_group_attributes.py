"""A provider's group attributes and importers (WP-057 S5c; lane B's step 0 spike).

- Names come from the provider's alias only, so one provider's importers can never write
  another's attributes (lane C's ask (a)); nothing in a request names them.
- OIDC only for now (SAML's freshness is unproven): `idp_groups_saml_unsupported`.
- Following off appends nothing; on, three FORCE importers and a FORCE `seen` marker.
- Following turned off (or the set-up removed) clears what its sign-ins left (ask (b)); the
  API never changes the user profile (that needs manage-realm, never the identity account's).
"""

import asyncio

import pytest

from app.modules.identity_access.domain import sso
from app.modules.identity_access.service import sso as service


def test_the_names_come_from_the_alias_only() -> None:
    names = sso.group_attributes("sx-acme-1a2b")
    assert names.all() == (
        "sx_groups_sx_acme_1a2b",
        "sx_groups_seen_sx_acme_1a2b",
        "sx_groups_overage_sx_acme_1a2b",
        "sx_groups_hasgroups_sx_acme_1a2b",
    )


def test_a_providers_importers_only_ever_name_its_own_attributes() -> None:
    mine, theirs = "sx-acme-1a2b", "sx-other-9f9f"
    found = sso.group_mappers("oidc", mine, groups_claim=f"groups sx_groups_{theirs}")
    targets = {m["config"].get("user.attribute") or m["config"]["attribute"] for m in found}
    assert targets == set(sso.group_attributes(mine).all())
    assert not any(theirs.replace("-", "_") in t for t in targets)
    assert {m["config"]["syncMode"] for m in found} == {"FORCE"}
    claims = [m["config"]["claim"] for m in found if "claim" in m["config"]]
    assert claims[1:] == ["_claim_names", "hasgroups"]
    (seen,) = [m for m in found if m["identityProviderMapper"] == "hardcoded-attribute-idp-mapper"]
    assert seen["config"] == {
        "attribute": sso.group_attributes(mine).seen,
        "attribute.value": "1",
        "syncMode": "FORCE",
    }


def test_saml_cannot_follow_groups_yet() -> None:
    with pytest.raises(sso.GroupsUnsupportedError) as error:
        sso.group_mappers("saml", "sx-acme-1a2b", "groups")
    assert error.value.code == "idp_groups_saml_unsupported"


def test_following_off_appends_nothing_and_on_appends_the_four() -> None:
    plain = sso.mappers("oidc", sso.OIDC_MAPPING)
    off = sso.mappers("oidc", sso.OIDC_MAPPING, alias="sx-acme-1a2b", groups_claim=None)
    on = sso.mappers("oidc", sso.OIDC_MAPPING, alias="sx-acme-1a2b", groups_claim="groups")
    assert plain == off
    assert on[: len(plain)] == plain
    assert len(on) == len(plain) + 4
    with pytest.raises(ValueError, match="alias"):
        sso.mappers("oidc", sso.OIDC_MAPPING, groups_claim="groups")


@pytest.mark.parametrize(
    ("settings", "claim"),
    [
        (None, None),
        ({}, None),
        ({"groups": {"follow": False, "claim": "groups"}}, None),
        ({"groups": {"follow": "yes", "claim": "groups"}}, None),
        ({"groups": {"follow": True, "claim": ""}}, None),
        ({"groups": {"follow": True, "claim": "roles"}}, "roles"),
    ],
)
def test_the_set_ups_groups_setting_is_read_strictly(
    settings: dict[str, object] | None, claim: str | None
) -> None:
    assert service._groups_claim(settings) == claim  # noqa: SLF001 - the setting's one reader


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def clear_group_attributes(self, alias: str) -> int:
        self.calls.append(f"clear {alias}")
        return 1


def test_following_off_clears_what_sign_ins_left_and_on_touches_nothing() -> None:
    off = _Recorder()
    asyncio.run(service._sync_group_attributes(off, "sx-a", None))  # type: ignore[arg-type]  # noqa: SLF001 - a recorder for the one call
    assert off.calls == ["clear sx-a"]
    on = _Recorder()
    asyncio.run(service._sync_group_attributes(on, "sx-c", "groups"))  # type: ignore[arg-type]  # noqa: SLF001 - as above
    assert on.calls == []  # never a user-profile change (manage-realm): nothing to declare


@pytest.mark.parametrize("alias", ["sx-a_b", "sx_a-b", "SX-acme-1a2b3c", "sx acme", ""])
def test_an_alias_outside_lowercase_digits_and_hyphens_is_refused(alias: str) -> None:
    """`-` becomes `_` in the names: `sx-a_b` and `sx_a-b` would share one (lane C, #632)."""
    with pytest.raises(ValueError, match="lowercase letters, digits and hyphens"):
        sso.group_attributes(alias)


def test_every_alias_alias_for_makes_is_accepted() -> None:
    names = sso.group_attributes(sso.alias_for("acme-corp-2", "1a2b3c"))
    assert names.groups == "sx_groups_sx_acme_corp_2_1a2b3c"


def test_a_long_slug_keeps_the_whole_token_so_aliases_never_collide() -> None:
    """Lane C's #632 note: `[:60]` used to cut the token off a long slug's alias."""
    slug = "a" * 61 + "-z"  # 63 characters, the longest a slug may be
    first, second = sso.alias_for(slug, "1a2b3c"), sso.alias_for(slug, "4d5e6f")
    assert first != second
    assert first.endswith("-1a2b3c")
    assert second.endswith("-4d5e6f")
    assert len(first) <= sso.ALIAS_MAX
    # The slug's room is 50 with a 6-character token: a cut just after a hyphen is trimmed.
    edge = sso.alias_for("a" * 49 + "-" + "b" * 10, "1a2b3c")
    assert edge == "sx-" + "a" * 49 + "-1a2b3c"
    assert "--" not in edge
    sso.group_attributes(first)  # still one-to-one with its attribute names


def test_a_short_slug_alias_is_unchanged() -> None:
    assert sso.alias_for("acme", "1a2b3c") == "sx-acme-1a2b3c"


@pytest.mark.parametrize("token", ["", "abc", "A1B2C3", "1a2b3c" * 10, "1a2b3c-"])
def test_a_token_outside_6_to_12_lowercase_hex_is_refused(token: str) -> None:
    """Lane C's #634 note: a long token would leave no room for the slug (or go negative)."""
    with pytest.raises(ValueError, match="6 to 12 lowercase hex"):
        sso.alias_for("acme", token)
