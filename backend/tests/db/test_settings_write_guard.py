"""The server refuses settings writes to people without the right (Chrome QA part 3, P3-01..05).

QA reached the Files, Security, Branding, Notifications, Mail, Directories, Requests and Portal
setup screens as a technician and as the team lead persona (who holds the built-in service desk
manager role) by typing their addresses. The screens are lane C's to gate (#303); this proves the
API itself refuses, whatever the screen offers.

Every settings write below is sent by each person with a body that passes validation, so the
answer is the permission decision, not a 422. A technician is refused every one (403); a
service desk manager only those outside the service desk's own configuration. "Nothing changed"
is shown by the audit log: every settings write is audited (`audited(...)`), and none of the
refused people has a single successful settings entry.
"""

import uuid
from typing import Any

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import CONSOLE, Org, World

pytestmark = [pytest.mark.db, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixture, used by name

MATCH = {"If-Match": '"1"'}
# 403; or 404 where a module hides that the page exists (the audit log, D-076).
REFUSED = frozenset({403, 404})
# (screen, method, path, body). The bodies are valid and change nothing a refusal would hide.
WRITES: tuple[tuple[str, str, str, dict[str, Any]], ...] = (
    (
        "files",
        "PUT",
        "/files/settings/rules",
        {"max_file_mb": 1, "max_batch": 1, "blocked_extensions": []},
    ),
    ("security", "PUT", "/identity/settings", {}),
    ("branding", "PUT", "/organization/branding/settings", {}),
    ("notifications", "PUT", "/notifications/rules/incident.created", {"enabled": False}),
    ("mail", "PUT", "/integrations/connector-settings", {}),
    ("mail", "POST", "/integrations/mailboxes", {}),
    ("directories", "POST", "/integrations/directories", {}),
    ("directories", "POST", "/integrations/ldap-directories", {}),
    ("organisation", "PATCH", "/organization/settings", {}),
    ("roles", "PUT", "/access-settings", {}),
    ("audit", "PUT", "/audit/settings", {}),
    ("assets", "PATCH", "/assets/settings", {}),
    ("ai", "PATCH", "/ai/settings", {}),
    ("catalog", "PATCH", "/catalog/settings", {}),
    ("knowledge", "PATCH", "/knowledge/settings", {}),
    ("reports", "PATCH", "/reports/settings", {}),
    # The service desk's own configuration (config.service_desk, sla.manage ...).
    ("requests", "PATCH", "/service-requests/settings", {}),
    ("incidents", "PATCH", "/incidents/settings", {}),
    ("portal", "PATCH", "/portal/settings", {}),
    ("sla", "PATCH", "/sla/record-types/incident/settings", {}),
    ("announcements", "PUT", "/announcements/settings", {}),
    ("routing", "PUT", "/automation/routing-settings", {}),
)
# What the built-in service desk manager may configure by design (WP-042: config.service_desk,
# sla.manage, automation.manage, config.announcements; no settings.manage).
DESK_SCREENS = frozenset({"requests", "incidents", "portal", "sla", "announcements", "routing"})


async def _desk_manager(world: World, org: Org, user: uuid.UUID) -> None:
    roles = (await world.call("GET", "/roles", org, org.admin)).json()
    (role,) = [r["id"] for r in roles if r["key"] == "service_desk_manager"]
    granted = await world.call("PUT", f"/users/{user}/roles/{role}", org, org.admin)
    assert granted.status_code in {200, 204}, granted.text


async def _send(world: World, org: Org, user: uuid.UUID, method: str, path: str, body: Any) -> Any:  # noqa: ANN401 - JSON
    return await world.call(method, path, org, user, json=body, headers={**CONSOLE, **MATCH})


async def _settings_entries(world: World, org: Org, user: uuid.UUID) -> list[str]:
    rows = await world.sql(
        "SELECT action FROM audit_entries WHERE tenant_id = $1 AND actor_id = $2"
        " AND outcome = 'done' AND (action LIKE '%settings%' OR action LIKE '%rule%'"
        " OR action LIKE '%mailbox%' OR action LIKE '%director%' OR action LIKE '%branding%')",
        org.tenant,
        user,
    )
    return [r["action"] for r in rows]


async def test_a_technician_is_refused_every_settings_write(world: World) -> None:
    a = world.a
    for screen, method, path, body in WRITES:
        refused = await _send(world, a, a.tech_a, method, path, body)
        assert refused.status_code in REFUSED, (screen, path, refused.status_code, refused.text)
    assert await _settings_entries(world, a, a.tech_a) == []  # nothing was written


async def test_the_desk_manager_writes_only_the_desk_configuration(world: World) -> None:
    a = world.a
    await _desk_manager(world, a, a.tech_c)
    for screen, method, path, body in WRITES:
        answer = await _send(world, a, a.tech_c, method, path, body)
        if screen in DESK_SCREENS:
            assert answer.status_code not in REFUSED, (screen, path, answer.text)
        else:
            assert answer.status_code in REFUSED, (screen, path, answer.status_code, answer.text)
    written = await _settings_entries(world, a, a.tech_c)
    outside = [w for w in written if not w.startswith(_DESK_PREFIXES)]
    assert outside == [], outside


_DESK_PREFIXES = ("service_request.", "incident.", "portal.", "sla.", "announcement", "automation.")


async def test_reads_follow_the_view_right(world: World) -> None:
    """GET answers only what the person's view right allows: a technician reads no admin page."""
    a = world.a
    for path in (
        "/identity/settings",
        "/notifications/rules",
        "/integrations/directories",
        "/integrations/mailboxes",
        "/access-settings",
        "/audit/settings",
    ):
        read = await world.call("GET", path, a, a.tech_a)
        assert read.status_code in REFUSED, (path, read.status_code)
    # Open to everyone signed in by design: the upload screen refuses a too-big or blocked file
    # before sending it (D-082). Reading the limits is not changing them.
    assert (await world.call("GET", "/files/settings/rules", a, a.tech_a)).status_code == 200
