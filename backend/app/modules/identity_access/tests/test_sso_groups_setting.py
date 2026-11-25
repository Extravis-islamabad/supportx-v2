"""The groups setting of a single sign-on set-up (WP-057 S5c-1b; lane B's conditions). No I/O."""

import pytest

from app.modules.identity_access.domain.sso import GroupsSetting, groups_problems


def test_off_is_always_allowed_whatever_the_claim_or_protocol() -> None:
    assert groups_problems("saml", GroupsSetting(follow=False, claim="email")) == []
    assert groups_problems("oidc", None) == []


def test_saml_cannot_follow_groups_yet() -> None:
    found = groups_problems("saml", GroupsSetting(follow=True, claim="groups"))
    assert [(p.field, p.code) for p in found] == [("groups", "idp_groups_saml_unsupported")]


@pytest.mark.parametrize(
    ("claim", "code"),
    [
        ("email", "idp_groups_claim_reserved"),  # an address would become a group ID
        ("preferred_username", "idp_groups_claim_reserved"),
        ("sx_groups_other", "idp_groups_claim_invalid"),  # never our own attributes
        ("", "idp_groups_claim_invalid"),
        ("g" * 129, "idp_groups_claim_invalid"),
        ("groups;drop", "idp_groups_claim_invalid"),
    ],
)
def test_a_claim_is_a_plain_name_of_the_providers_own(claim: str, code: str) -> None:
    found = groups_problems("oidc", GroupsSetting(follow=True, claim=claim))
    assert [(p.field, p.code) for p in found] == [("groups.claim", code)]


@pytest.mark.parametrize("claim", ["groups", "roles", "https://acme.test/claims/groups"])
def test_the_usual_claims_are_accepted(claim: str) -> None:
    assert groups_problems("oidc", GroupsSetting(follow=True, claim=claim)) == []
