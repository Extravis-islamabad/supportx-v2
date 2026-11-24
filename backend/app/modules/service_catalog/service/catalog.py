"""Catalog items (WP-030 s1, WP-031 s1; REQ-SR-001, -005..008, -010, -021..023, -046, REQ-CAT).

Reading: staff (anyone holding `catalog_items.manage`, or a technician) see every item, in any
status; everyone else sees published items open to everyone whose category they may browse
(REQ-SR-010 AC3, plan D1, D3, D7). Writing needs `catalog_items.manage`, follows If-Match, keeps
field history and emits an event in the same transaction. Every reference is checked through its
own module's public interface (work_items through the ports, as it depends on the catalog).

Life (plan D3): a new item is a draft. Publishing checks it is complete (domain/catalog.py); a
published item can be retired and published again; a retired or published item never goes back
to draft. A planned `publish_at` / `retire_at` is applied by the schedule (service/schedule.py).
Copy makes an independent draft. Delete is soft and only for an item no request names (409
offering retire otherwise).
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.modules import licensing, sla
from app.modules.identity_access import Subject, user_contacts
from app.modules.organization import existing_unit_ids
from app.modules.service_catalog.domain.catalog import (
    DESCRIPTION_MAX,
    MAX_EXTRA_CATEGORIES,
    SUMMARY_MAX,
    ItemKind,
    ItemStatus,
    PublishFacts,
    copy_names,
    icon_problems,
    keyword_problems,
    missing_translations,
    publish_problems,
    schedule_problems,
    subject_from,
    subject_template_problems,
    text_problems,
)
from app.modules.service_catalog.domain.items import (
    LANGUAGES,
    ApprovalStage,
    Approver,
    ApproverKind,
    AutoRule,
    EscalationTarget,
    ItemAudience,
    ItemRules,
    PlannedTask,
    PlanStepKind,
    Question,
    QuestionAudience,
    QuestionKind,
    RestartOn,
    StageRule,
    TaskField,
    TaskFieldKind,
    TaskOwnerKind,
    answer_problems,
    name_problems,
    needs_approval,
    request_again,
    rules_problems,
    uses_stages,
)
from app.modules.service_catalog.events import CatalogItemChanged
from app.modules.service_catalog.infra.models import CatalogItem
from app.modules.service_catalog.service import categories, ports
from app.modules.service_catalog.service.common import (
    MANAGE,
    invalid,
    is_staff,
    require_manage,
)
from app.shared.clock import Clock, SystemClock
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, ChangeKind, Source, record_changes
from app.shared.richtext import sanitize_html

ITEM_RECORD_TYPE = "catalog_item"
SR_TYPE = "service_request"  # the SLA policies an item may name
PRIORITIES = frozenset({"p1", "p2", "p3", "p4"})
# The words of a copy's name, per language (data, kept with the copy; plan D3).
COPY_PREFIX = {"en": "Copy of", "ar": "نسخة من", "ur": "نقل:"}
# What a write may set, as stored. `status` changes through `set_status` rules only.
# REQ-SR-014's quantity is Professional (D-133): the licence's catalogue feature.
CATALOG_FEATURE = "catalog"

ITEM_FIELDS = (
    "category_id",
    "names",
    "descriptions",
    "audience",
    "questions",
    "approval",
    "plan",
    "default_priority",
    "requester_sets_priority",
    "sla_policy_id",
    "group_id",
    "technician_id",
    "technician_after_approval",
    "count_approval_time",
    "auto_fulfil",
    # WP-047a S1
    "max_quantity",
    "asks_needed_by",
    # WP-031 s1
    "kind",
    "template_id",
    "summaries",
    "keywords",
    "icon",
    "owner_id",
    "featured",
    "sort_order",
    "subject_template",
    "requesters_see_approval",
    "extra_category_ids",
    "publish_at",
    "retire_at",
)
_IDS = ("category_id", "sla_policy_id", "group_id", "technician_id", "template_id", "owner_id")


class ItemRepository(Repository[CatalogItem]):
    """Items: versioned updates with If-Match."""

    model = CatalogItem


# --- JSON <-> domain ------------------------------------------------------------------------------


def _uuid(value: Any) -> uuid.UUID | None:  # noqa: ANN401 - JSON value
    return None if value in {None, ""} else uuid.UUID(str(value))


def _question(q: Mapping[str, Any]) -> Question:
    return Question(
        q["key"],
        q.get("label", {}),
        QuestionKind(q["kind"]),
        bool(q.get("required", False)),
        tuple(q.get("options", ())),
        option_labels=dict(q.get("option_labels") or {}),
        help=dict(q.get("help") or {}),
        default=q.get("default"),
        shown_to=frozenset(
            QuestionAudience(a) for a in q.get("shown_to") or list(QuestionAudience)
        ),
        restarts_approval=bool(q.get("restarts_approval", False)),
    )


def rules_of(item: CatalogItem) -> ItemRules:
    """The item's rules as the domain sees them (also for work_items, through the package)."""
    stages = stages_of(item.approval)
    stage = stages[0] if stages else None
    return ItemRules(
        questions=tuple(_question(q) for q in item.questions),
        approval=stage,
        plan=tuple(planned_task(t) for t in item.plan),
        technician_after_approval=item.technician_after_approval,
        count_approval_time=item.count_approval_time,
        auto_fulfil=item.auto_fulfil,
        stages=stages,
        restart_on=restart_on_of(item.approval),
    )


def _task_field(f: Mapping[str, Any]) -> TaskField:
    return TaskField(
        key=str(f.get("key", "")),
        label=dict(f.get("label") or {}),
        kind=TaskFieldKind(f.get("kind") or TaskFieldKind.TEXT.value),
        required=bool(f.get("required", False)),
        options=tuple(str(o) for o in f.get("options") or ()),
        requester_visible=bool(f.get("requester_visible", False)),
    )


def planned_task(t: Mapping[str, Any]) -> PlannedTask:
    """One stored plan step as the domain sees it (WP-047a S5 adds keys, order, fields, owner)."""
    owner_kind = t.get("owner_kind")
    return PlannedTask(
        t.get("title", {}),
        _uuid(t.get("group_id")),
        _uuid(t.get("owner_id")),
        bool(t.get("required", True)),
        bool(t.get("internal", False)),
        key=t.get("key"),
        waits_for=tuple(str(w) for w in t.get("waits_for") or ()),
        condition=t.get("condition"),
        fields=tuple(_task_field(f) for f in t.get("fields") or ()),
        owner_kind=TaskOwnerKind(owner_kind) if owner_kind else None,
        question_key=t.get("question_key"),
        kind=PlanStepKind(t.get("kind") or PlanStepKind.TASK.value),
    )


def restart_on_of(approval: Mapping[str, Any] | None) -> frozenset[RestartOn]:
    """The request values whose change restarts approval (WP-047a S3b; REQ-SR-041)."""
    return frozenset(
        RestartOn(code)
        for code in (approval or {}).get("restart_on") or []
        if code in set(RestartOn)
    )


def _stage(raw: Mapping[str, Any]) -> ApprovalStage:
    return ApprovalStage(
        approvers=tuple(
            Approver(
                ApproverKind(a["kind"]),
                _uuid(a.get("person_id")),
                group_id=_uuid(a.get("group_id")),
                question_key=a.get("question_key"),
            )
            for a in raw.get("approvers", [])
        ),
        backup_id=_uuid(raw.get("backup_id")),
        comments_required=bool(raw.get("comments_required", False)),
        self_approval=bool(raw.get("self_approval", False)),
        rule=StageRule(raw.get("rule") or StageRule.ANY.value),
        parallel_group=raw.get("parallel_group"),
        condition=raw.get("condition"),
        auto_earlier=raw.get("auto_earlier"),
        auto_rules=tuple(
            AutoRule(dict(r.get("name") or {}), r.get("condition") or {})
            for r in raw.get("auto_rules") or []
        ),
        escalate_to=EscalationTarget(raw.get("escalate_to") or EscalationTarget.BACKUP.value),
    )


def stages_of(approval: Mapping[str, Any] | None) -> tuple[ApprovalStage, ...]:
    """An item's approval stages, in order (WP-047a S2a).

    Stored as `{"stages": [...]}`; an item saved before S2a keeps its one stage at the top
    level and reads as that one stage, unchanged (no data step, the coordinator's condition 5).
    """
    if not approval:
        return ()
    # `stages: null` or `[]` (the API model's default on a single-stage body) is the single
    # stage, as `_stored_approval` stores it.
    if approval.get("stages"):
        return tuple(_stage(raw) for raw in approval["stages"])
    return (_stage(approval),)


def _shape_problems(values: Mapping[str, Any]) -> list[tuple[str, str]]:  # noqa: C901, PLR0912 - one rule per field, flat
    """Types and codes of the incoming fields (before the domain rules)."""
    found: list[tuple[str, str]] = []
    if "audience" in values and values["audience"] not in set(ItemAudience):
        found.append(("audience", "invalid_choice"))
    if "kind" in values and values["kind"] not in set(ItemKind):
        found.append(("kind", "invalid_choice"))
    if "default_priority" in values and values["default_priority"] not in (PRIORITIES | {None}):
        found.append(("default_priority", "invalid_choice"))
    found += [
        (name, "invalid_value")
        for name in ("names", "descriptions", "summaries", "keywords")
        if name in values and not isinstance(values[name], Mapping)
    ]
    if "names" in values and isinstance(values["names"], Mapping):
        found += name_problems("names", values["names"], required=True)
    if isinstance(values.get("summaries"), Mapping):
        found += text_problems("summaries", values["summaries"], limit=SUMMARY_MAX)
    if isinstance(values.get("descriptions"), Mapping):
        found += text_problems("descriptions", values["descriptions"], limit=DESCRIPTION_MAX)
    if isinstance(values.get("keywords"), Mapping):
        found += keyword_problems(values["keywords"])
    found += icon_problems("icon", values.get("icon"))
    if len(values.get("extra_category_ids") or []) > MAX_EXTRA_CATEGORIES:
        found.append(("extra_category_ids", "too_many_categories"))
    for i, q in enumerate(values.get("questions") or []):
        if not isinstance(q, Mapping) or q.get("kind") not in set(QuestionKind):
            found.append((f"questions.{i}.kind", "invalid_choice"))
        elif any(a not in set(QuestionAudience) for a in q.get("shown_to") or []):
            found.append((f"questions.{i}.shown_to", "invalid_choice"))
    approval = values.get("approval")
    if approval is not None:
        if not isinstance(approval, Mapping):
            found.append(("approval", "invalid_value"))
        else:
            found += _approval_shape(approval)
    return found


def _stage_shape(stage: Mapping[str, Any], at: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for i, a in enumerate(stage.get("approvers") or []):
        if not isinstance(a, Mapping) or a.get("kind") not in set(ApproverKind):
            found.append((f"{at}.approvers.{i}.kind", "invalid_choice"))
    if stage.get("rule") is not None and stage.get("rule") not in set(StageRule):
        found.append((f"{at}.rule", "invalid_choice"))
    if stage.get("auto_earlier") is not None and not isinstance(stage["auto_earlier"], bool):
        found.append((f"{at}.auto_earlier", "invalid_value"))
    rules = stage.get("auto_rules")
    if rules is not None and (
        not isinstance(rules, list)
        or not all(isinstance(r, Mapping) and isinstance(r.get("name"), Mapping) for r in rules)
    ):
        found.append((f"{at}.auto_rules", "invalid_value"))
    if stage.get("escalate_to") is not None and stage["escalate_to"] not in set(EscalationTarget):
        found.append((f"{at}.escalate_to", "invalid_choice"))  # WP-047a S3a (REQ-SR-034)
    return found


def _approval_shape(approval: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The raw approval's shape before it is parsed: one stage, or a `stages` list (S2a)."""
    restart = approval.get("restart_on")
    if restart is not None and (
        not isinstance(restart, list) or any(r not in set(RestartOn) for r in restart)
    ):
        return [("approval.restart_on", "invalid_choice")]  # WP-047a S3b
    if approval.get("stages") is None:  # today's single stage (or `stages: null`)
        return _stage_shape(approval, "approval")
    stages = approval["stages"]
    if not isinstance(stages, list) or not all(isinstance(x, Mapping) for x in stages):
        return [("approval.stages", "invalid_value")]
    found: list[tuple[str, str]] = []
    for n, stage in enumerate(stages):
        found += _stage_shape(stage, f"approval.stages.{n}")
    return found


def _stored_question(q: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "key": q["key"],
        "label": dict(q.get("label") or {}),
        "kind": q["kind"],
        "required": bool(q.get("required", False)),
        "options": list(q.get("options") or []),
        "option_labels": {k: dict(v) for k, v in (q.get("option_labels") or {}).items()},
        "help": dict(q.get("help") or {}),
        "default": q.get("default"),
        "shown_to": sorted(set(q.get("shown_to") or [a.value for a in QuestionAudience])),
        **({"restarts_approval": True} if q.get("restarts_approval") else {}),
    }


def _stored_approval(approval: Mapping[str, Any]) -> dict[str, Any]:  # noqa: C901 - one rule per part, flat
    """The approval as it is stored: one shape only (WP-047a S2a).

    `{"stages": [...]}` when stages are given, else the single stage. A stage with nothing new
    is stored exactly as before S2a (approvers with `kind` and `person_id`, the backup and the
    two switches: the coordinator's condition 5); S2a's parts are added only when set. IDs as
    text.
    """

    def text(value: Any) -> str | None:  # noqa: ANN401 - an ID as given (UUID or text)
        return None if value is None else str(value)

    def approver(raw: Mapping[str, Any]) -> dict[str, Any]:
        kept: dict[str, Any] = {"kind": raw["kind"], "person_id": text(raw.get("person_id"))}
        if raw.get("group_id") is not None:
            kept["group_id"] = text(raw["group_id"])
        if raw.get("question_key") is not None:
            kept["question_key"] = raw["question_key"]
        return kept

    def stage(raw: Mapping[str, Any]) -> dict[str, Any]:
        kept: dict[str, Any] = {
            "approvers": [approver(a) for a in raw.get("approvers") or []],
            "backup_id": text(raw.get("backup_id")),
            "comments_required": bool(raw.get("comments_required", False)),
            "self_approval": bool(raw.get("self_approval", False)),
        }
        if raw.get("rule") not in (None, StageRule.ANY.value):
            kept["rule"] = str(raw["rule"])
        for name in ("parallel_group", "condition", "auto_earlier"):
            if raw.get(name) is not None:
                kept[name] = raw[name]
        if raw.get("escalate_to") not in (None, EscalationTarget.BACKUP.value):  # S3a
            kept["escalate_to"] = str(raw["escalate_to"])
        if raw.get("auto_rules"):  # WP-047a S2b (REQ-SR-033)
            kept["auto_rules"] = [
                {"name": dict(r["name"]), "condition": r["condition"]} for r in raw["auto_rules"]
            ]
        return kept

    # WP-047a S3b (REQ-SR-041): which of the request's own values restart approval, on both shapes.
    restart = sorted({str(c) for c in approval.get("restart_on") or []})
    extra = {"restart_on": restart} if restart else {}
    if approval.get("stages"):
        return {"stages": [stage(s) for s in approval["stages"]], **extra}
    return {**stage(approval), **extra}


def stored(values: Mapping[str, Any]) -> dict[str, Any]:  # noqa: C901 - one rule per field, flat
    """The fields as the columns keep them (IDs as text inside the JSON, HTML sanitised)."""
    out = {k: values[k] for k in ITEM_FIELDS if k in values}
    if isinstance(out.get("approval"), Mapping):
        out["approval"] = _stored_approval(out["approval"])
    for name in _IDS:
        if name in out:
            out[name] = _uuid(out[name])
    if "extra_category_ids" in out:
        out["extra_category_ids"] = list(
            dict.fromkeys(uuid.UUID(str(c)) for c in out["extra_category_ids"] or [])
        )
    for name in ("publish_at", "retire_at"):
        if isinstance(out.get(name), str):
            out[name] = datetime.fromisoformat(out[name])
    if out.get("descriptions") is not None:
        out["descriptions"] = {
            lang: sanitize_html(html) for lang, html in out["descriptions"].items() if html
        }
    if out.get("summaries") is not None:
        out["summaries"] = {k: v.strip() for k, v in out["summaries"].items() if v.strip()}
    if out.get("keywords") is not None:
        out["keywords"] = {
            lang: list(dict.fromkeys(w.strip() for w in words if w.strip()))
            for lang, words in out["keywords"].items()
        }
    if out.get("questions") is not None:
        out["questions"] = [_stored_question(q) for q in out["questions"]]
    if out.get("plan") is not None:
        out["plan"] = [
            {
                "title": dict(t.get("title") or {}),
                "group_id": None if t.get("group_id") is None else str(t["group_id"]),
                "owner_id": None if t.get("owner_id") is None else str(t["owner_id"]),
                "required": bool(t.get("required", True)),
                "internal": bool(t.get("internal", False)),
                # WP-047a S5 (REQ-SR-047..050, -056): kept only when set.
                **{
                    k: t[k]
                    for k in ("key", "condition", "owner_kind", "question_key")
                    if t.get(k) is not None
                },
                **({"waits_for": list(t["waits_for"])} if t.get("waits_for") else {}),
                **({"fields": [dict(f) for f in t["fields"]]} if t.get("fields") else {}),
                **({"kind": t["kind"]} if t.get("kind") not in (None, "task") else {}),
            }
            for t in out["plan"]
        ]
    return out


async def _group_problems(
    session: AsyncSession, item: CatalogItem, rules: ItemRules
) -> list[tuple[str, str]]:
    staged = _staged_named(rules)
    stage_groups = {at: g for at, (kind, g) in staged.items() if kind == "group"}
    wanted = {g for g in (item.group_id, *(t.group_id for t in rules.plan)) if g is not None}
    wanted |= set(stage_groups.values())
    known = await existing_unit_ids(session, "group", sorted(wanted, key=str))
    found = [("group_id", "not_found")] if item.group_id not in {None, *known} else []
    found += [(at, "not_found") for at, group in stage_groups.items() if group not in known]
    return found + [
        (f"plan.{i}.group_id", "not_found")
        for i, task in enumerate(rules.plan)
        if task.group_id is not None and task.group_id not in known
    ]


def _staged_named(rules: ItemRules) -> dict[str, tuple[str, uuid.UUID]]:
    """Every person and group the stages name, by field path (WP-047a S2a; #582 review).

    Each stage's named approvers, groups and backup are checked like stage 1's, so no stage
    can name an ID that is not this tenant's.
    """
    several = len(rules.stages) > 1  # one stage's people are `approval.*`, checked already
    named: dict[str, tuple[str, uuid.UUID]] = {}
    for n, stage in enumerate(rules.stages):
        at = f"approval.stages.{n}" if several else "approval"
        for i, a in enumerate(stage.approvers):
            if a.person_id is not None and several:
                named[f"{at}.approvers.{i}.person_id"] = ("person", a.person_id)
            if a.group_id is not None:
                named[f"{at}.approvers.{i}.group_id"] = ("group", a.group_id)
        if stage.backup_id is not None and several:
            named[f"{at}.backup_id"] = ("person", stage.backup_id)
    return named


def _people_named(item: CatalogItem, rules: ItemRules) -> dict[str, uuid.UUID]:
    people: dict[str, uuid.UUID] = {}
    if item.technician_id is not None:
        people["technician_id"] = item.technician_id
    if item.owner_id is not None:
        people["owner_id"] = item.owner_id
    if rules.approval is not None:
        people |= {
            f"approval.approvers.{i}.person_id": a.person_id
            for i, a in enumerate(rules.approval.approvers)
            if a.person_id is not None
        }
        if rules.approval.backup_id is not None:
            people["approval.backup_id"] = rules.approval.backup_id
    people |= {
        f"plan.{i}.owner_id": task.owner_id
        for i, task in enumerate(rules.plan)
        if task.owner_id is not None
    }
    people |= {at: who for at, (kind, who) in _staged_named(rules).items() if kind == "person"}
    return people


async def _reference_problems(
    session: AsyncSession, item: CatalogItem, rules: ItemRules
) -> list[tuple[str, str]]:
    """Every ID the item names exists in this tenant (through each module's public interface)."""
    found: list[tuple[str, str]] = []
    wanted = [c for c in (item.category_id, *(item.extra_category_ids or [])) if c is not None]
    live = await categories.live_category_ids(session, wanted)
    if item.category_id is not None and item.category_id not in live:
        found.append(("category_id", "not_found"))
    if any(c not in live for c in item.extra_category_ids or []):
        found.append(("extra_category_ids", "not_found"))
    if item.sla_policy_id is not None and not await sla.existing_policy_ids(
        session, SR_TYPE, [item.sla_policy_id]
    ):
        found.append(("sla_policy_id", "not_found"))
    if (
        item.template_id is not None
        and await ports.entry_template(session, item.template_id) is None
    ):
        found.append(("template_id", "not_found"))
    found += await _group_problems(session, item, rules)
    people = _people_named(item, rules)
    known = await user_contacts(session, sorted({str(p) for p in people.values()}))
    return found + [(at, "not_found") for at, person in people.items() if str(person) not in known]


# --- views ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemView:
    """An item for a screen: the row, its rules and whether the viewer may change it."""

    item: CatalogItem
    rules: ItemRules
    can_manage: bool

    @property
    def missing_translations(self) -> list[tuple[str, str]]:
        """(field, language) still to translate (plan D5); for managers only."""
        if not self.can_manage:
            return []
        texts: dict[str, Mapping[str, str] | None] = {
            "names": self.item.names,
            "summaries": self.item.summaries,
            "descriptions": self.item.descriptions,
        }
        for i, q in enumerate(self.rules.questions):
            texts[f"questions.{i}.label"] = q.label
            texts[f"questions.{i}.help"] = q.help
            for code, words in q.option_labels.items():
                texts[f"questions.{i}.option_labels.{code}"] = words
        for i, t in enumerate(self.rules.plan):
            texts[f"plan.{i}.title"] = t.title
        return missing_translations(texts, LANGUAGES)


async def offered(session: AsyncSession, subject: Subject) -> Select[CatalogItem]:
    """The items a viewer may see: staff all live ones, others what is offered to them."""
    query = select(CatalogItem).where(CatalogItem.deleted_at.is_(None))
    if is_staff(subject):
        return query
    hidden = sorted(await categories.hidden_ids(session), key=str)
    query = query.where(
        CatalogItem.status == ItemStatus.PUBLISHED.value,
        CatalogItem.audience == ItemAudience.EVERYONE.value,
    )
    if hidden:
        query = query.where(
            or_(CatalogItem.category_id.is_(None), CatalogItem.category_id.not_in(hidden))
        )
    return query


async def list_items(
    session: AsyncSession,
    subject: Subject,
    *,
    category_id: uuid.UUID | None = None,
    statuses: Sequence[ItemStatus] = (),
    featured: bool | None = None,
) -> list[ItemView]:
    """The items the viewer may see, in their order (a category also lists its extra items)."""
    query = await offered(session, subject)
    if category_id is not None:
        query = query.where(
            or_(
                CatalogItem.category_id == category_id,
                CatalogItem.extra_category_ids.contains([category_id]),
            )
        )
    if statuses:
        query = query.where(CatalogItem.status.in_([s.value for s in statuses]))
    if featured is not None:
        query = query.where(CatalogItem.featured.is_(featured))
    rows = list(
        await session.scalars(
            query.order_by(CatalogItem.sort_order, CatalogItem.created_at, CatalogItem.id)
        )
    )
    manage = subject.holds(MANAGE)
    return [ItemView(r, rules_of(r), manage) for r in rows]


POPULAR_DAYS = 90  # "most requested" looks back this far (WP-032 D1)


async def popular_items(session: AsyncSession, subject: Subject, *, limit: int) -> list[ItemView]:
    """The items the viewer may see, most requested first over the last 90 days (REQ-CAT-027).

    Items nobody requested in that time are left out; ties keep the catalog's own order.
    """
    since = datetime.now(UTC) - timedelta(days=POPULAR_DAYS)
    counts = await ports.request_counts(session, since)
    if not counts:
        return []
    query = await offered(session, subject)
    rows = list(
        await session.scalars(
            query.where(CatalogItem.id.in_(list(counts))).order_by(
                CatalogItem.sort_order, CatalogItem.created_at, CatalogItem.id
            )
        )
    )
    rows.sort(key=lambda r: -counts.get(r.id, 0))  # stable: the catalog order breaks ties
    manage = subject.holds(MANAGE)
    return [ItemView(r, rules_of(r), manage) for r in rows[:limit]]


async def get_item(session: AsyncSession, subject: Subject, item_id: uuid.UUID) -> ItemView:
    """One item the viewer may see; otherwise 404."""
    row = await session.scalar((await offered(session, subject)).where(CatalogItem.id == item_id))
    if row is None:
        raise NotFound(code="catalog_item_not_found")
    return ItemView(row, rules_of(row), subject.holds(MANAGE))


async def expected_delivery(session: AsyncSession, item: CatalogItem) -> sla.DeliveryTarget | None:
    """How long a request for `item` usually takes, from the SLA that would apply.

    The item's own policy, else the requests' fallback, at its default priority (Haider,
    2026-11-10). None when no SLA applies; the form then says nothing about delivery.
    """
    return await sla.delivery_target(session, SR_TYPE, item.sla_policy_id, item.default_priority)


async def expected_delivery_at(session: AsyncSession, item: CatalogItem) -> datetime | None:
    """When a request for `item` raised now should be delivered (REQ-SR-015 AC1; WP-047a S1).

    The same SLA as `expected_delivery`, counted from now on its calendar (the item's group's
    when the target uses the group calendar), as the request itself will be.
    """
    return await sla.delivery_at(
        session,
        SR_TYPE,
        item.sla_policy_id,
        item.default_priority,
        datetime.now(UTC),
        group_id=item.group_id,
    )


def snapshot(item: CatalogItem) -> dict[str, Any]:
    """The item's fields as field history keeps them (IDs and times as text)."""
    out: dict[str, Any] = {}
    for name in (*ITEM_FIELDS, "status"):
        value = getattr(item, name)
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif isinstance(value, datetime):
            value = value.isoformat()
        elif name == "extra_category_ids":
            value = [str(v) for v in value or []]
        out[name] = value
    return out


async def _check(session: AsyncSession, item: CatalogItem, clock: Clock) -> None:
    """The rules, the references, the schedule and, for a published item, completeness."""
    rules = rules_of(item)
    problems = (
        rules_problems(rules)
        + subject_template_problems(item.subject_template, rules.questions)
        + await _reference_problems(session, item, rules)
    )
    if item.kind == ItemKind.INCIDENT_TEMPLATE.value and (rules.questions or rules.plan):
        problems.append(("kind", "not_allowed"))  # the template decides the incident's form
    status = ItemStatus(item.status)
    problems += schedule_problems(status, item.publish_at, item.retire_at, clock.now())
    if status is ItemStatus.PUBLISHED or item.publish_at is not None:
        problems += publish_problems(facts_of(item))
    if problems:
        raise invalid(list(dict.fromkeys(problems)))


def facts_of(item: CatalogItem) -> PublishFacts:
    """What publishing the item depends on."""
    return PublishFacts(
        names=item.names,
        kind=ItemKind(item.kind),
        group_id=item.group_id,
        category_id=item.category_id,
        template_id=item.template_id,
    )


async def record_item_change(
    session: AsyncSession,
    item: CatalogItem,
    changes: list[Change],
    *,
    kind: ChangeKind,
    source: Source,
) -> None:
    """Field history and the outbox event of a change, in the caller's transaction."""
    await record_changes(
        session,
        record_type=ITEM_RECORD_TYPE,
        record_id=item.id,
        version=item.version,
        kind=kind,
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        CatalogItemChanged(item_id=item.id, changed_fields=[c.field for c in changes]),
        aggregate_id=item.id,
        aggregate_version=item.version,
    )


def _initial_status(values: Mapping[str, Any]) -> ItemStatus:
    """A new item is a draft, or published when asked (`enabled`: the WP-030 spelling)."""
    if "status" in values:
        status = ItemStatus(values["status"])
        if status is ItemStatus.RETIRED:
            raise invalid([("status", "not_allowed")])
        return status
    return ItemStatus.PUBLISHED if values.get("enabled") is True else ItemStatus.DRAFT


async def requester_question_keys(
    session: AsyncSession, item_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, frozenset[str]]:
    """Per item, the keys of the questions its requesters see (REQ-CAT-008; WP-047a S1).

    For the portal's answers, filtered on the server: an answer is shown to its requester only
    when its question is theirs (default deny: a removed question's answer, or a technician's or
    an approver's, never reaches them). Read as system data: the caller already decided the
    record is the requester's to see.
    """
    if not item_ids:
        return {}
    rows = await session.execute(
        select(CatalogItem.id, CatalogItem.questions).where(CatalogItem.id.in_(set(item_ids)))
    )
    return {
        item_id: frozenset(
            q["key"]
            for q in questions or []
            if QuestionAudience.REQUESTER.value
            in (q.get("shown_to") or [a.value for a in QuestionAudience])
        )
        for item_id, questions in rows.all()
    }


@dataclass(frozen=True)
class AgainForm:
    """Request again from a past request (REQ-SR-016): the item's form with its answers.

    `available` false with `reason` (a label code) when the item can no longer be requested
    (AC3: retired, or no longer offered to this person); then nothing else is given.
    """

    item_id: uuid.UUID
    available: bool
    reason: str | None
    answers: Mapping[str, Any]
    dropped: tuple[str, ...]


def _unavailable(item_id: uuid.UUID, reason: str) -> AgainForm:
    return AgainForm(item_id=item_id, available=False, reason=reason, answers={}, dropped=())


async def again_form(
    session: AsyncSession, subject: Subject, item_id: uuid.UUID, answers: Mapping[str, Any]
) -> AgainForm:
    """The item as it is now (no item versions yet, the coordinator's Q8), prefilled (S1)."""
    try:
        view = await get_item(session, subject, item_id)
    except NotFound:
        row = await session.get(CatalogItem, item_id)
        retired = row is not None and row.status == ItemStatus.RETIRED.value
        reason = "catalog_item_retired" if retired else "catalog_item_unavailable"
        return _unavailable(item_id, reason)
    item = view.item
    if item.status != ItemStatus.PUBLISHED.value or item.kind != ItemKind.SERVICE.value:
        retired = item.status == ItemStatus.RETIRED.value
        reason = "catalog_item_retired" if retired else "catalog_item_unavailable"
        return _unavailable(item_id, reason)
    again = request_again(view.rules.questions, answers)
    return AgainForm(
        item_id=item_id, available=True, reason=None, answers=again.answers, dropped=again.dropped
    )


async def templated_subject(
    session: AsyncSession, item_id: uuid.UUID, answers: Mapping[str, Any], *, person: str
) -> str | None:
    """A new request's subject from its item's template, or None without one (WP-031 leftover).

    Choice answers show their English words (the stored fallback language, never a code);
    `person` is the requested-for person's name.
    """
    item = await session.get(CatalogItem, item_id)
    if item is None or not item.subject_template:
        return None
    words = {
        code: str(labels.get("en") or code)
        for q in rules_of(item).questions
        for code, labels in q.option_labels.items()
    }
    filled = subject_from(item.subject_template, answers, person=person, words=words)
    return filled or None


async def quantity_licensed(subject: Subject) -> bool:
    """Whether the tenant's plan offers a quantity on requests (REQ-SR-014: `catalog`)."""
    return await licensing.has_feature(subject.tenant_id, CATALOG_FEATURE)


async def _quantity_licensed(subject: Subject, values: Mapping[str, Any]) -> None:
    """A quantity on an item is Professional (REQ-SR-014, D-133): `catalog`, on the server.

    Turning it off (null) is always allowed, so a downgraded tenant can clear it.
    """
    if values.get("max_quantity") is not None:
        await licensing.require_feature(subject.tenant_id, CATALOG_FEATURE)
    # WP-047a S2a: approval stages beyond today's one are Professional too; saving an item back
    # to a single stage of today's kinds is always allowed (a downgraded tenant can simplify).
    approval = values.get("approval")
    if isinstance(approval, Mapping) and uses_stages(stages_of(approval)):
        await licensing.require_feature(subject.tenant_id, CATALOG_FEATURE)


async def create_item(
    session: AsyncSession,
    subject: Subject,
    values: Mapping[str, Any],
    *,
    source: Source,
    clock: Clock | None = None,
) -> ItemView:
    """A new item (names in English at least), a draft unless published at once."""
    require_manage(subject)
    clock = clock or SystemClock()
    if problems := _shape_problems({"names": {}, **values}):
        raise invalid(problems)
    await _quantity_licensed(subject, values)
    status = _initial_status(values)
    item = CatalogItem(
        **{
            "descriptions": {},
            "summaries": {},
            "keywords": {},
            "questions": [],
            "plan": [],
            "extra_category_ids": [],
            "kind": ItemKind.SERVICE.value,
            **stored(values),
            "status": status.value,
            "published_at": clock.now() if status is ItemStatus.PUBLISHED else None,
        }
    )
    await _check(session, item, clock)
    await ItemRepository(session).add(item)
    after = snapshot(item)
    await record_item_change(
        session,
        item,
        [Change(k, None, v) for k, v in after.items() if v not in (None, [], {})],
        kind="created",
        source=source,
    )
    return ItemView(item, rules_of(item), can_manage=True)


async def _live(session: AsyncSession, item_id: uuid.UUID) -> CatalogItem:
    row = await session.scalar(
        select(CatalogItem).where(CatalogItem.id == item_id, CatalogItem.deleted_at.is_(None))
    )
    if row is None:
        raise NotFound(code="catalog_item_not_found")
    return row


def _status_change(row: CatalogItem, values: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """The status columns a write asks for (plan D3), or nothing."""
    if "status" in values:
        wanted = ItemStatus(values["status"])
    elif "enabled" in values:  # WP-030 spelling: on = published, off = retired
        wanted = ItemStatus.PUBLISHED if values["enabled"] else ItemStatus.RETIRED
        if wanted is ItemStatus.RETIRED and row.status == ItemStatus.DRAFT.value:
            return {}
    else:
        return {}
    current = ItemStatus(row.status)
    if wanted is current:
        return {}
    if wanted is ItemStatus.DRAFT or (
        wanted is ItemStatus.RETIRED and current is not ItemStatus.PUBLISHED
    ):
        raise invalid([("status", "not_allowed")])
    if wanted is ItemStatus.PUBLISHED:
        return {
            "status": wanted.value,
            "publish_at": None,
            "published_at": row.published_at or now,
        }
    return {"status": wanted.value, "retire_at": None}


async def update_item(  # noqa: PLR0913 - the item, its version and the change
    session: AsyncSession,
    subject: Subject,
    item_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
    clock: Clock | None = None,
) -> ItemView:
    """Change an item; unchanged input keeps the version and emits nothing."""
    require_manage(subject)
    clock = clock or SystemClock()
    row = await _live(session, item_id)
    if problems := _shape_problems(values):
        raise invalid(problems)
    await _quantity_licensed(subject, values)
    before = snapshot(row)
    wanted = {**stored(values), **_status_change(row, values, clock.now())}
    changes = {k: v for k, v in wanted.items() if getattr(row, k) != v}
    if not changes:
        if row.version != expected_version:
            raise Conflict(
                code="version_conflict",
                params={"expected_version": expected_version, "current_version": row.version},
            )
        return ItemView(row, rules_of(row), can_manage=True)
    probe = CatalogItem(
        **{
            **{k: getattr(row, k) for k in (*ITEM_FIELDS, "status", "published_at")},
            **changes,
        }
    )
    await _check(session, probe, clock)
    updated = await ItemRepository(session).update(
        row.id, expected_version=expected_version, changes=changes
    )
    after = snapshot(updated)
    changed = [Change(k, before[k], after[k]) for k in after if before[k] != after[k]]
    await record_item_change(
        session,
        updated,
        changed,
        kind="status" if set(changes) & {"status"} else "updated",
        source=source,
    )
    return ItemView(updated, rules_of(updated), can_manage=True)


async def copy_item(
    session: AsyncSession, subject: Subject, item_id: uuid.UUID, *, source: Source
) -> ItemView:
    """An independent draft with the item's settings, named "Copy of …" (REQ-CAT-005)."""
    require_manage(subject)
    row = await _live(session, item_id)
    values = {k: getattr(row, k) for k in ITEM_FIELDS}
    # A copy is a new item: the same edition gates as saving one (lane C's #582 review), so a
    # downgraded tenant cannot copy stages or a quantity into a new item.
    await _quantity_licensed(subject, values)
    values |= {
        "names": copy_names(row.names, COPY_PREFIX),
        "featured": False,
        "publish_at": None,
        "retire_at": None,
    }
    copy = CatalogItem(**values, status=ItemStatus.DRAFT.value)
    await ItemRepository(session).add(copy)
    after = snapshot(copy)
    await record_item_change(
        session,
        copy,
        [Change(k, None, v) for k, v in after.items() if v not in (None, [], {})]
        + [Change("copied_from", None, str(row.id))],
        kind="created",
        source=source,
    )
    return ItemView(copy, rules_of(copy), can_manage=True)


async def delete_item(  # noqa: PLR0913 - the item, its version, the source and the clock
    session: AsyncSession,
    subject: Subject,
    item_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
    clock: Clock | None = None,
) -> None:
    """Soft delete an item no request names; 409 offering retire otherwise (plan D3)."""
    require_manage(subject)
    clock = clock or SystemClock()
    row = await _live(session, item_id)
    if used := await ports.item_usage(session, row.id):
        raise Conflict(code="catalog_item_in_use", params={"requests": used})
    updated = await ItemRepository(session).soft_delete(row.id, expected_version=expected_version)
    await record_item_change(
        session, updated, [Change("deleted_at", None, "deleted")], kind="deleted", source=source
    )


# --- for work_items: what an item decides for a new request ---------------------------------------


@dataclass(frozen=True)
class PlanStep:
    """One task of the item's fulfilment plan, as plain values (REQ-SR-046)."""

    title: Mapping[str, str]  # per language
    group_id: uuid.UUID | None
    owner_id: uuid.UUID | None
    required: bool
    internal: bool
    # WP-047a S5 (REQ-SR-047..050, -056), as plain values for work_items' plan.
    key: str | None = None
    waits_for: tuple[str, ...] = ()
    condition: Mapping[str, Any] | None = None
    fields: tuple[Mapping[str, Any], ...] = ()  # key, label, kind, required, options, visible
    owner_kind: str | None = None  # person | requested_for_manager | person_answer
    question_key: str | None = None
    kind: str = "task"  # task | asset_handover


@dataclass(frozen=True)
class ApproverSpec:
    """One approver of a stage as plain values (WP-047a S2a): a kind code and what it names."""

    kind: str
    person_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    question_key: str | None = None


@dataclass(frozen=True)
class StageSpec:
    """One approval stage as plain values, for the request's snapshot (WP-047a S2a).

    Configuration only: codes and IDs, never names or e-mail addresses (snapshot condition 1).
    """

    approvers: tuple[ApproverSpec, ...]
    rule: str = "any"
    backup_id: uuid.UUID | None = None
    comments_required: bool = False
    self_approval: bool = False
    parallel_group: str | None = None
    condition: Mapping[str, Any] | None = None
    # WP-047a S2b (REQ-SR-033): the item's own "approved earlier" (None: the tenant's) and its
    # automatic rules, each (name per language, condition).
    auto_earlier: bool | None = None
    auto_rules: tuple[tuple[Mapping[str, str], Mapping[str, Any]], ...] = ()
    # WP-047a S3a (REQ-SR-034): where it goes after its last reminder (an EscalationTarget code).
    escalate_to: str = "backup"


@dataclass(frozen=True)
class RequestItem:
    """What a service request takes from its item (plain values; work_items decides with them)."""

    item_id: uuid.UUID
    needs_approval: bool
    default_priority: str | None
    sla_policy_id: uuid.UUID | None
    group_id: uuid.UUID | None
    technician_id: uuid.UUID | None
    technician_after_approval: bool
    count_approval_time: bool
    auto_fulfil: bool
    # WP-047a S1: how many may be asked for (None: no quantity), and whether needed-by is asked.
    max_quantity: int | None
    asks_needed_by: bool
    answer_problems: tuple[tuple[str, str], ...]  # the answers checked against the form
    # The approval stage (WP-030 s2), as plain values for work_items' engine: each approver as
    # (manager of the requested-for person?, person id), the backup, and the stage's switches.
    approvers: tuple[tuple[bool, uuid.UUID | None], ...] = ()
    backup_id: uuid.UUID | None = None
    self_approval: bool = False
    comments_required: bool = False
    plan: tuple[PlanStep, ...] = ()  # WP-030 s3: the fulfilment tasks, in order
    requesters_see_approval: bool = True  # WP-031 plan D8
    # WP-047a S2a: every stage in order (the single-stage fields above stay for stage 1).
    stages: tuple[StageSpec, ...] = ()
    # The keys of its "person" questions: each answer must name a live person of the tenant,
    # which work_items checks on the server (lane B's and the coordinator's #582 review).
    person_questions: tuple[str, ...] = ()
    # Whether the stages engine runs it: the catalog's one answer (`uses_stages`), the same one
    # that gates saving, so the save and the raise can never disagree (lane C's #582 review).
    uses_stages: bool = False
    # WP-047a S3b (REQ-SR-041): what restarts approval when it changes after submitting: the
    # marked questions' keys, and `quantity` / `requested_for` when the item says so.
    restart_keys: tuple[str, ...] = ()


async def request_item(
    session: AsyncSession,
    subject: Subject,
    item_id: uuid.UUID,
    answers: Mapping[str, Any],
) -> RequestItem:
    """The item a person raises a request from, if they may (published, open to them); else 404.

    A "report a problem" entry is not a service request item (it raises an incident).
    """
    view = await get_item(session, subject, item_id)
    item = view.item
    if item.status != ItemStatus.PUBLISHED.value or item.kind != ItemKind.SERVICE.value:
        raise NotFound(code="catalog_item_not_found")
    return _decides(item, answers)


def _decides(item: CatalogItem, answers: Mapping[str, Any]) -> RequestItem:
    rules = rules_of(item)
    stage = rules.approval
    return RequestItem(
        item_id=item.id,
        needs_approval=needs_approval(rules),
        default_priority=item.default_priority,
        sla_policy_id=item.sla_policy_id,
        group_id=item.group_id,
        technician_id=item.technician_id,
        technician_after_approval=rules.technician_after_approval,
        count_approval_time=rules.count_approval_time,
        auto_fulfil=rules.auto_fulfil,
        max_quantity=item.max_quantity,
        asks_needed_by=item.asks_needed_by,
        answer_problems=tuple(answer_problems(rules.questions, answers)),
        approvers=tuple(
            (a.kind is ApproverKind.REQUESTED_FOR_MANAGER, a.person_id)
            for a in (stage.approvers if stage else ())
        ),
        backup_id=stage.backup_id if stage else None,
        self_approval=stage.self_approval if stage else False,
        comments_required=stage.comments_required if stage else False,
        plan=tuple(
            PlanStep(
                title=dict(t.title),
                group_id=t.group_id,
                owner_id=t.owner_id,
                required=t.required,
                internal=t.internal,
                key=t.key,
                waits_for=tuple(t.waits_for),
                condition=t.condition,
                fields=tuple(
                    {
                        "key": f.key,
                        "label": dict(f.label),
                        "kind": f.kind.value,
                        "required": f.required,
                        "options": list(f.options),
                        "requester_visible": f.requester_visible,
                    }
                    for f in t.fields
                ),
                owner_kind=t.owner_kind.value if t.owner_kind else None,
                question_key=t.question_key,
                kind=t.kind.value,
            )
            for t in rules.plan
        ),
        requesters_see_approval=item.requesters_see_approval,
        stages=tuple(_spec(s) for s in (rules.stages or ((stage,) if stage else ()))),
        person_questions=tuple(q.key for q in rules.questions if q.kind is QuestionKind.PERSON),
        uses_stages=uses_stages(rules.stages),
        restart_keys=tuple(
            sorted(
                {q.key for q in rules.questions if q.restarts_approval}
                | {r.value for r in rules.restart_on}
            )
        ),
    )


def _spec(stage: ApprovalStage) -> StageSpec:
    return StageSpec(
        approvers=tuple(
            ApproverSpec(a.kind.value, a.person_id, a.group_id, a.question_key)
            for a in stage.approvers
        ),
        rule=stage.rule.value,
        backup_id=stage.backup_id,
        comments_required=stage.comments_required,
        self_approval=stage.self_approval,
        parallel_group=stage.parallel_group,
        condition=stage.condition,
        auto_earlier=stage.auto_earlier,
        auto_rules=tuple((dict(r.name), r.condition) for r in stage.auto_rules),
        escalate_to=stage.escalate_to.value,
    )


async def item_decides(session: AsyncSession, item_id: uuid.UUID) -> RequestItem | None:
    """What an existing request's item says, for a step after submission (WP-030 s2).

    Read by the system (the technician after approval): no viewer check and deleted or retired
    items included, since the request already exists and its approver may not see the item.
    """
    row = await session.get(CatalogItem, item_id)
    return None if row is None else _decides(row, {})


async def item_decides_with(
    session: AsyncSession, item_id: uuid.UUID, answers: Mapping[str, Any]
) -> RequestItem | None:
    """As `item_decides`, with `answers` checked against the item's form (`answer_problems`).

    WP-047a S3b (REQ-SR-041): changed answers on an existing request are checked as the raise
    checks them, against the item as it is now (items have no versions yet, the plan's Q8).
    """
    row = await session.get(CatalogItem, item_id)
    return None if row is None else _decides(row, answers)


__all__ = [
    "MANAGE",
    "ApproverSpec",
    "ItemView",
    "PlanStep",
    "RequestItem",
    "StageSpec",
    "copy_item",
    "create_item",
    "delete_item",
    "facts_of",
    "get_item",
    "item_decides",
    "item_decides_with",
    "list_items",
    "offered",
    "record_item_change",
    "request_item",
    "rules_of",
    "snapshot",
    "stored",
    "update_item",
]
