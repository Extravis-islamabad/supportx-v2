"""AD/LDAP federation rules (WP-040, D-118): Keycloak component and mappers, refusals. No I/O."""

from dataclasses import replace

from app.modules.integrations.domain.ldap import (
    CHANGED_SYNC_SECONDS,
    LdapSettings,
    Security,
    Vendor,
    component,
    mappers,
    problems,
)

AD = LdapSettings(
    host="dc1.corp.example",
    port=636,
    security=Security.LDAPS,
    vendor=Vendor.ACTIVE_DIRECTORY,
    bind_dn="CN=svc-supportx,OU=Service,DC=corp,DC=example",
    users_dn="OU=Staff,DC=corp,DC=example",
)


def test_an_ldaps_directory_is_read_only_and_synced_every_30_minutes() -> None:
    assert problems(AD) == []
    body = component(AD, name="Corp AD", realm_id="r-1", bind_password="b1nd")
    config = body["config"]
    assert (body["providerId"], body["parentId"]) == ("ldap", "r-1")
    assert config["connectionUrl"] == ["ldaps://dc1.corp.example:636"]
    assert config["startTls"] == ["false"]
    assert config["editMode"] == ["READ_ONLY"]  # never writes to the customer's directory
    assert config["changedSyncPeriod"] == [str(CHANGED_SYNC_SECONDS)]
    assert config["usernameLDAPAttribute"] == ["sAMAccountName"]
    assert config["trustEmail"] == ["false"]


def test_plain_ldap_needs_the_audited_choice_and_start_tls_does_not() -> None:
    plain = replace(AD, security=Security.PLAIN, port=389)
    assert problems(plain) == [("security", "plain_connection_refused")]
    assert problems(replace(plain, allow_plain=True)) == []
    start_tls = replace(AD, security=Security.START_TLS, port=389)
    assert problems(start_tls) == []
    config = component(start_tls, name="x", realm_id="r", bind_password="p")["config"]
    assert (config["connectionUrl"], config["startTls"]) == (
        ["ldap://dc1.corp.example:389"],
        ["true"],
    )


def test_bad_hosts_names_and_filters_are_refused_by_field() -> None:
    bad = replace(
        AD,
        host="dc1/../evil",
        port=0,
        bind_dn="not a dn",
        users_dn="",
        user_filter="objectClass=user",
        department_from="dept;drop",
        changed_sync_seconds=10,
    )
    assert {f for f, _ in problems(bad)} == {
        "host",
        "port",
        "bind_dn",
        "users_dn",
        "user_filter",
        "department_from",
        "changed_sync_seconds",
    }


def test_mappers_bring_what_supportx_maps_and_ad_disables_at_sign_in() -> None:
    found = {
        m["name"]: m
        for m in mappers(replace(AD, groups_dn="OU=Groups,DC=corp,DC=example"), component_id="c-1")
    }
    assert found["email"]["config"]["ldap.attribute"] == ["mail"]
    assert found["department"]["config"]["user.model.attribute"] == ["sx_department"]
    assert found["site"]["config"]["user.model.attribute"] == ["sx_site"]
    assert found["account controls"]["providerId"] == "msad-user-account-control-mapper"
    assert found["groups"]["config"]["mode"] == ["READ_ONLY"]
    assert all(m["parentId"] == "c-1" for m in found.values())
    other = {m["name"] for m in mappers(replace(AD, vendor=Vendor.OTHER), component_id="c-1")}
    assert "account controls" not in other
    assert "groups" not in other  # no groups DN, no group mapper
