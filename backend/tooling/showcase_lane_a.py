"""Lane A's showcase data (QA6-DATA-01, QA6-SR-01): approvers, service requests, problems.

Called from tooling/showcase_seed.py's `fill`, through the public API as the seed's sign-ins.
Idempotent: every record is found by its subject first and made once with an idempotency key.

- **Approvers (QA6-SR-01).** Each requester gets the signed-in technician as their manager,
  so a request needing "the manager's approval" has someone who can decide it. The admin
  never approves their own request.
- **Service requests.** Seven from the published starter catalogue, in every state: waiting
  for approval (2), approved and in progress, fulfilled (resolved), closed, rejected and
  withdrawn.
- **Problems.** Three, two of them known errors with their symptoms and workaround, each
  linked to some of the incidents the seed made.

- **Business rules.** Three enabled ones that send new records to a group; they run on
  records made after them, so the seeded records above stay as they are.
"""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

TEXT = "Showcase request"
DAY = "2026-12-01"


class Api(Protocol):
    """The seed's API helper (tooling/showcase_seed.Api)."""

    async def call(  # noqa: PLR0913 - mirrors the helper
        self,
        method: str,
        path: str,
        *,
        json: Any = None,  # noqa: ANN401 - request bodies of every endpoint
        params: Mapping[str, Any] | None = None,
        idempotency: str | None = None,
        version: int | None = None,
    ) -> Any:  # noqa: ANN401 - the endpoint's JSON
        """One request."""
        ...

    async def all_pages(self, path: str, params: Mapping[str, Any] | None = None) -> list[Any]:
        """Every row of a cursor-paged list."""
        ...

    def as_user(self, user: uuid.UUID) -> "Api":
        """The same API as someone else."""
        ...


def _key(*parts: str) -> str:
    return str(uuid.uuid5(uuid.UUID("5ca5e5ee-a000-4000-8000-000000000000"), "/".join(parts)))


async def ensure_managers(api: Api, requesters: Sequence[str], manager: uuid.UUID) -> int:
    """Each requester without a manager gets one who can approve (QA6-SR-01)."""
    done = 0
    for person in requesters:
        found = await api.call("GET", f"/api/v1/users/{person}")
        if found.get("manager_id"):
            continue
        await api.call(
            "PATCH",
            f"/api/v1/users/{person}/person",
            json={"manager_id": str(manager)},
            version=found["version"],
        )
        done += 1
    return done


# A plausible answer per question kind; choices take their first option.
ANSWERS: dict[str, Any] = {
    "date": DAY,
    "datetime": f"{DAY}T09:00:00Z",
    "number": 1,
    "decimal": 1,
    "currency": 1,
    "yes_no": True,
    "email": "someone@showcase.test",
    "url": "https://showcase.test",
    "phone": "+92 300 0000000",
}


def _answers(item: Mapping[str, Any]) -> dict[str, Any]:
    """A plausible answer to every required question of an item."""
    found: dict[str, Any] = {}
    for q in item.get("questions") or []:
        if not q.get("required"):
            continue
        options = q.get("options") or []
        if q.get("kind") == "choice" and options:
            found[q["key"]] = options[0]
        elif q.get("kind") == "multi_choice" and options:
            found[q["key"]] = [options[0]]
        else:
            found[q["key"]] = ANSWERS.get(q.get("kind") or "", TEXT)
    return found


# (subject, state): every state a request can be in.
REQUESTS = (
    ("New laptop for the finance team", "awaiting_approval"),
    ("Access to the reporting tool", "awaiting_approval"),
    ("Second monitor for the help desk", "in_progress"),
    ("VPN access for a new starter", "fulfilled"),
    ("Mobile phone for the field engineer", "closed"),
    ("Admin rights on a shared laptop", "rejected"),
    ("Parking pass for the visitor", "withdrawn"),
)


SR = "/api/v1/service-requests"


class Rules(Protocol):
    """The type's settings the moves need (tooling/showcase_seed.Catalogue)."""

    @property
    def closure_codes(self) -> list[str]:
        """The closure codes in use."""
        ...

    def reason(self, action: str, status: str) -> dict[str, Any]:
        """The reason fields a move needs, if any."""
        ...


async def _decide(deciders: Sequence[Api], record_id: str, decision: str) -> bool:
    """The first of `deciders` with the request waiting for them decides it."""
    for api in deciders:
        mine = await api.call("GET", f"{SR}/my-approvals")
        row = next((r for r in mine["items"] if r["record_id"] == record_id), None)
        if row is None:
            continue
        await api.call(
            "POST",
            f"{SR}/{record_id}/approvals/{row['approval_id']}/decision",
            json={
                "decision": decision,
                "comment": None if decision == "approve" else "Not within the policy.",
            },
            version=row["approval_version"],
        )
        return True
    return False


async def _move(
    api: Api, rules: Rules, record_id: str, action: str, extra: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """One status move with the reason it needs; returns the record after it."""
    record = await api.call("GET", f"{SR}/{record_id}")
    moved = await api.call(
        "POST",
        f"{SR}/{record_id}/actions/{action}",
        json={**rules.reason(action, record["status"]), **(extra or {})},
        version=record["version"],
    )
    return dict(moved)


async def ensure_service_requests(  # noqa: PLR0913 - the seed's sign-ins and lookups, explicit
    admin: Api,
    approver: Api,
    *,
    rules: Rules,
    requesters: Sequence[str],
    worker: tuple[str, str],
    admin_id: str,
) -> int:
    """Seven requests from the starter catalogue in every state; returns how many were made.

    `worker` is the group and technician who fulfil them. The withdrawn one is the admin's own
    (only someone who signs in can withdraw); the others are requesters', decided by their
    manager, or by the approval administrators when the item names someone else.
    """
    items = await admin.call("GET", "/api/v1/catalog/items", params={"status": "published"})
    needing = [i for i in items if i.get("approval")]
    if not needing:
        return 0
    existing = {r["subject"] for r in await admin.all_pages(SR)}
    made = 0
    for n, (subject, state) in enumerate(REQUESTS):
        if subject in existing:
            continue
        item = needing[n % len(needing)]
        requester = admin_id if state == "withdrawn" else requesters[(n * 3) % len(requesters)]
        record = await admin.call(
            "POST",
            SR,
            json={
                "subject": subject,
                "requester_id": requester,
                "catalog_item_id": item["id"],
                "answers": _answers(item),
            },
            idempotency=_key("request", subject),
        )
        made += 1
        if state == "awaiting_approval":
            continue
        if state == "withdrawn":
            fresh = await admin.call("GET", f"{SR}/{record['id']}")
            await admin.call("POST", f"{SR}/{record['id']}/withdraw", version=fresh["version"])
            continue
        decision = "reject" if state == "rejected" else "approve"
        if not await _decide((approver, admin), record["id"], decision) or state == "rejected":
            continue
        fresh = await admin.call("GET", f"{SR}/{record['id']}")
        if fresh["status"] == "new":
            await admin.call(
                "POST",
                f"{SR}/{record['id']}/assign",
                json={
                    "group_id": worker[0],
                    "technician_id": worker[1],
                    **rules.reason("assign", fresh["status"]),
                },
                version=fresh["version"],
            )
        await _move(admin, rules, record["id"], "start_work")
        if state == "in_progress":
            continue
        await _move(
            admin,
            rules,
            record["id"],
            "resolve",
            {
                "resolution": "<p>Delivered and set up with the requester.</p>",
                "confirm_open_work": True,
            },
        )
        if state == "closed":
            await _move(
                admin,
                rules,
                record["id"],
                "close",
                {
                    "closure_code": rules.closure_codes[0] if rules.closure_codes else None,
                    "confirm_open_work": True,
                },
            )
    return made


# (subject, symptoms, workaround or None, known error)
PROBLEMS = (
    (
        "Mail relay drops messages at peak hours",
        "<p>Users see error 4.4.2 when sending between 09:00 and 10:00.</p>",
        "<p>Resend after a few minutes, or restart the relay service.</p>",
        True,
    ),
    (
        "VPN disconnects every hour",
        "<p>The VPN client drops the tunnel after about 60 minutes.</p>",
        "<p>Reconnect; the session resumes without signing in again.</p>",
        True,
    ),
    ("Printers on floor 3 go offline", "<p>Jobs queue but never print.</p>", None, False),
)


def _number(display_id: str) -> int:
    return int(display_id.rsplit("-", 1)[-1])


async def ensure_problems(api: Api, owner: str, incidents: Sequence[Mapping[str, Any]]) -> int:
    """Three problems, two known errors, each with linked incidents; returns how many were made.

    Idempotent (QA9-F-02): a problem is found by its subject (the seed's stable key) and is never
    made twice; its incidents are picked by display number, which never changes (the list's
    order does, once records are backdated or worked on); an incident already caused by a
    problem is left as it is; a known error is marked once. A run that stopped half way is
    finished by the next. Never deletes.
    """
    existing = {p["subject"]: p for p in await api.all_pages("/api/v1/problems")}
    ordered = [i["id"] for i in sorted(incidents, key=lambda i: _number(i["display_id"]))]
    made = 0
    for n, (subject, symptoms, workaround, known) in enumerate(PROBLEMS):
        record = existing.get(subject)
        if record is None:
            record = await api.call(
                "POST",
                "/api/v1/problems",
                json={
                    "subject": subject,
                    "requester_id": owner,
                    "symptoms": symptoms,
                    **({"workaround": workaround} if workaround else {}),
                },
                idempotency=_key("problem", subject),
            )
            made += 1
        wanted = ordered[n * 2 : n * 2 + 2]
        caused: set[str] = set()
        if wanted:
            preview = await api.call(
                "POST", "/api/v1/problems/from-incidents/preview", json={"incident_ids": wanted}
            )
            caused = {c["incident_id"] for c in preview["already_caused"]}
        for incident in wanted:
            if incident in caused:
                continue  # linked already, to this problem or another: never moved
            await api.call(
                "POST",
                f"/api/v1/problems/{record['id']}/incidents",
                json={"incident_id": incident, "move": False},
            )
        if known:
            fresh = await api.call("GET", f"/api/v1/problems/{record['id']}")
            if fresh.get("known_error_at") is None:
                await api.call(
                    "POST",
                    f"/api/v1/problems/{record['id']}/known-error",
                    json={"comment": "Seen several times this month."},
                    version=fresh["version"],
                )
    return made


# (record type, name, conditions, the group it sends records to)
RULES: tuple[tuple[str, str, dict[str, Any] | None, str], ...] = (
    (
        "incident",
        "VPN faults go to Network and access",
        {"field": "subject", "op": "contains", "value": "VPN"},
        "Network and access",
    ),
    (
        "incident",
        "Printer faults go to the service desk",
        {"field": "subject", "op": "contains", "value": "printer"},
        "Service desk",
    ),
    ("service_request", "Requests without a group go to the service desk", None, "Service desk"),
)


async def ensure_rules(api: Api, groups: Mapping[str, str]) -> int:
    """Three enabled business rules, each once (by name); returns how many were made."""
    made = 0
    names: dict[str, set[str]] = {}
    for record_type, name, conditions, group in RULES:
        if record_type not in names:
            found = await api.call(
                "GET", "/api/v1/automation/rules", params={"record_type": record_type}
            )
            names[record_type] = {r["name"] for r in found}
        if name in names[record_type]:
            continue
        await api.call(
            "POST",
            "/api/v1/automation/rules",
            json={
                "record_type": record_type,
                "name": name,
                "events": ["create"],
                "conditions": conditions,
                "actions": [
                    {
                        "kind": "set",
                        "field": "group_id",
                        "value": groups[group],
                        "mode": "fill_empty",
                    }
                ],
                "state": "enabled",
            },
            idempotency=_key("rule", record_type, name),
        )
        made += 1
    return made


SLA = "/api/v1/sla/record-types/incident/policies"
# (name, Arabic, Urdu, condition on the incident or a group by name, response, resolution)
# Above the default policy, so the showcase's incidents show named SLAs with live countdowns;
# the rest keep the default (QA9, Haider).
SLA_POLICIES: tuple[
    tuple[str, str, str, dict[str, Any] | str, tuple[int, str], tuple[int, str]], ...
] = (
    (
        "Critical and high incidents",
        "الحوادث الحرجة وذات الأولوية العالية",
        "اہم اور زیادہ ترجیح والے واقعات",
        {"field": "priority", "op": "in", "value": ["p1", "p2"]},
        (30, "minutes"),
        (4, "hours"),
    ),
    (
        "Network and access faults",
        "أعطال الشبكة والوصول",
        "نیٹ ورک اور رسائی کی خرابیاں",
        "Network and access",
        (1, "hours"),
        (8, "hours"),
    ),
)


async def ensure_sla_policies(api: Api, groups: Mapping[str, str]) -> int:
    """The showcase's named incident SLA policies, each once (by name); returns how many were made.

    Made before the incidents, which take their SLA when they are created.
    """
    names = {p["name"] for p in await api.call("GET", SLA)}
    made = 0
    for name, arabic, urdu, condition, response, resolution in SLA_POLICIES:
        if name in names:
            continue
        conditions = (
            condition
            if isinstance(condition, dict)
            else {"field": "group_id", "op": "eq", "value": groups[condition]}
        )
        await api.call(
            "POST",
            SLA,
            json={
                "name": name,
                "labels": {"en": name, "ar": arabic, "ur": urdu},
                "conditions": conditions,
                "targets": [
                    {"kind": "first_response", "amount": response[0], "unit": response[1]},
                    {"kind": "resolution", "amount": resolution[0], "unit": resolution[1]},
                ],
            },
            idempotency=_key("sla_policy", name),
        )
        made += 1
    return made
