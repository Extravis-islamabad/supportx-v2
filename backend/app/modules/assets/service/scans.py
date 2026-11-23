"""Scan history per asset and the overdue-scan rule (WP-049b s3; REQ-AST-054, 056).

- **Scans (054):** `record_scan` is the port discovery will call (nothing calls it yet but
  tests): one append-only row per scan with its source, type, result (a failed one with its
  reason, AC3) and what changed (labelled kinds, domain/scans.py). A good scan moves the asset's
  `last_scanned_at`; a scan that changed something adds a line to the asset's history (a part,
  without a version bump). `assets.view` lists an asset's scans.
- **Retention (054 AC2):** the daily clean-up deletes scans older than the asset settings'
  retention (months, Appendix A: 6), per tenant with app.tenant_id set, and writes one audit
  summary per tenant run (count and cut-off). It is the only hard delete: the asset, its history
  lines and its last scan time stay.
- **Overdue rule (056):** off by default, set with `config.assets`. For chosen product types
  (and the types below them), an asset whose last good scan is older than N days is moved to a
  chosen state or to the trash (restorable, never deleted). Assets never scanned and disposed
  assets are left alone. Saving shows how many assets it affects now (AC2). It runs from a
  scheduled job per tenant; each run that changes something is recorded with what it changed
  and each asset's history names the rule (AC1). Moves follow the life cycle (the
  coordinator, 2026-11-11): the rule accepts only a state some life cycle of its product types
  can reach, and an asset whose own state has no move there (or whose move needs a permission
  or fields it lacks) is skipped, never forced, and listed in the run with its reason. A state's
  "reason required" is met by the rule itself, which its history names. The trash stays
  allowed (restorable).
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Select, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import AppError, NotFound
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.assets.domain.assets import counts_toward_limit
from app.modules.assets.domain.catalogue import AssetStateCategory, Problem
from app.modules.assets.domain.scans import (
    RETENTION_MONTHS_DEFAULT,
    RUN_LIST_MAX,
    OverdueAction,
    ScanFailure,
    ScanProblem,
    ScanResult,
    ScanSource,
    ScanType,
    clean_changes,
    failure_problem,
    rule_problems,
)
from app.modules.assets.events import OverdueRuleChanged, ScanRecorded
from app.modules.assets.infra.models import (
    Asset,
    AssetLifeCycle,
    AssetLifeCycleTransition,
    AssetOverdueRule,
    AssetOverdueRun,
    AssetProductType,
    AssetScan,
    AssetSettings,
    AssetState,
)
from app.modules.assets.service.assets import (
    RECORD_TYPE,
    VIEW,
    _refuse,
    _require,
    _reserve,
    _saved,
    _tenant,
    _visible,
)
from app.modules.assets.service.catalogue import SETTINGS_RECORD, _fresh, require_configure
from app.modules.assets.service.moves import _life_cycle_id, _missing, _moves
from app.modules.audit import WORKER, AuditActorType, record
from app.modules.identity_access import Subject
from app.shared.clock import system_clock
from app.shared.events import record_event
from app.shared.history import Change, Source, automated, record_changes
from app.shared.ids import new_id

log = get_logger(__name__)
SCANS_PAGE_MAX = 100
RULE_RECORD_TYPE = "asset_overdue_rule"
OVERDUE_REASON = "overdue_scan_rule"  # label asset_change_reason.overdue_scan_rule {{days}}
RULE_FIELDS = ("enabled", "days", "product_type_ids", "action", "state_id")
DELETE_BATCH = 5000
RUNS_LISTED = 20


# --- scans ------------------------------------------------------------------------------------


async def record_scan(  # noqa: PLR0913 - one scan: which asset, when, from where, how it went
    session: AsyncSession,
    *,
    asset_id: uuid.UUID,
    scanned_at: datetime,
    source: ScanSource,
    result: ScanResult,
    scan_type: ScanType | None = None,
    failure_reason: ScanFailure | None = None,
    changes: Sequence[Mapping[str, Any]] = (),
) -> AssetScan:
    """Record one scan of an asset of the session's tenant (the discovery port, REQ-AST-054)."""
    try:
        cleaned = clean_changes(changes)
    except ScanProblem as refused:
        _refuse([Problem(refused.field, refused.code)])
    if (failure := failure_problem(result, failure_reason)) is not None:
        _refuse([Problem(failure.field, failure.code)])
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise NotFound(code="asset_not_found")
    scan = AssetScan(
        id=new_id(),
        tenant_id=_tenant(session),
        asset_id=asset.id,
        scanned_at=scanned_at,
        source=source.value,
        scan_type=None if scan_type is None else scan_type.value,
        result=result.value,
        failure_reason=None if failure_reason is None else failure_reason.value,
        changes=[c.as_json() for c in cleaned],
    )
    session.add(scan)
    await session.flush()
    if result is ScanResult.OK and (
        asset.last_scanned_at is None or asset.last_scanned_at < scanned_at
    ):
        # The scan's own time, not a save of the asset: no version bump, no history of its own.
        await session.execute(
            update(Asset).where(Asset.id == asset.id).values(last_scanned_at=scanned_at)
        )
    if cleaned:
        part = str(scan.id)
        await record_changes(
            session,
            record_type=RECORD_TYPE,
            record_id=asset.id,
            version=asset.version,
            kind="child_added",
            changes=[Change("scan", None, part)],
            source="integration" if source is not ScanSource.IMPORT else "import",
        )
    await record_event(
        session,
        ScanRecorded(asset_id=asset.id, scan_id=scan.id, result=result.value, changes=len(cleaned)),
        aggregate_id=scan.id,
    )
    return scan


async def list_scans(
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    *,
    before: datetime | None = None,
    limit: int = 25,
) -> tuple[list[AssetScan], datetime | None]:
    """The asset's scans, newest first, and the cursor of the next page."""
    _require(subject, VIEW)
    await _visible(session, subject, asset_id)
    limit = max(1, min(limit, SCANS_PAGE_MAX))
    statement = select(AssetScan).where(AssetScan.asset_id == asset_id)
    if before is not None:
        statement = statement.where(AssetScan.scanned_at < before)
    rows = list(
        await session.scalars(
            statement.order_by(AssetScan.scanned_at.desc(), AssetScan.id.desc()).limit(limit + 1)
        )
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return rows, (rows[-1].scanned_at if more and rows else None)


def _months_back(now: datetime, months: int) -> datetime:
    """`now` minus whole months, on the same day (the month's last day when it is shorter)."""
    month = now.month - 1 - months
    year = now.year + month // 12
    month = month % 12 + 1
    day = min(now.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
                        31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])  # fmt: skip
    return now.replace(year=year, month=month, day=day)


async def clean_up_scans(
    session: AsyncSession, *, now: datetime | None = None
) -> tuple[int, datetime]:
    """Delete the tenant's scans older than its retention: (count, cut-off). The only delete."""
    settings = await session.get(AssetSettings, _tenant(session))
    months = RETENTION_MONTHS_DEFAULT if settings is None else settings.scan_retention_months
    cutoff = _months_back(now or system_clock.now(), months)
    total = 0
    while True:
        batch = select(AssetScan.id).where(AssetScan.scanned_at < cutoff).limit(DELETE_BATCH)
        result = await session.execute(delete(AssetScan).where(AssetScan.id.in_(batch)))
        count = int(getattr(result, "rowcount", 0) or 0)
        total += count
        if count < DELETE_BATCH:
            break
    return total, cutoff


async def _tenants(database: Database) -> list[uuid.UUID]:
    async with database.platform_session() as platform:
        return list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())


async def scan_cleanup_sweep(database: Database, settings: Settings) -> None:
    """Each tenant's old scans removed once a day, with one audit summary per tenant run."""
    del settings
    for tenant in await _tenants(database):
        async with database.tenant_session(TenantContext(tenant)) as session:
            deleted, cutoff = await clean_up_scans(session)
            await record(
                session,
                action_code="asset_scan.cleaned_up",
                facts=WORKER,
                actor=(AuditActorType.SYSTEM, None),
                object_type="asset_scans",
                details={"deleted": deleted, "cutoff": cutoff.isoformat()},
            )
        if deleted:
            log.info("asset_scans_cleaned_up", tenant_id=str(tenant), deleted=deleted)


# --- the overdue-scan rule --------------------------------------------------------------------


async def get_rule(session: AsyncSession) -> AssetOverdueRule:
    """The tenant's rule (made off, with Appendix A's 60 days, on first use)."""
    await session.execute(
        insert(AssetOverdueRule)
        .values(tenant_id=_tenant(session))
        .on_conflict_do_nothing(index_elements=[AssetOverdueRule.tenant_id])
    )
    row: AssetOverdueRule | None = await session.scalar(select(AssetOverdueRule))
    assert row is not None  # noqa: S101 - inserted above
    return row


async def _stored_rule(session: AsyncSession) -> AssetOverdueRule:
    """The tenant's rule as stored, or its defaults unsaved: a read that never writes (preview).

    The object is never added to the session, so nothing is flushed for it.
    """
    row: AssetOverdueRule | None = await session.scalar(select(AssetOverdueRule))
    if row is not None:
        return row
    return AssetOverdueRule(
        enabled=False, days=60, product_type_ids=[], action="move_state", state_id=None
    )


async def _type_tree(session: AsyncSession, roots: Sequence[uuid.UUID]) -> list[uuid.UUID]:
    parents = dict(
        (await session.execute(select(AssetProductType.id, AssetProductType.parent_id)))
        .tuples()
        .all()
    )
    found = set(roots)
    grew = True
    while grew:
        grew = False
        for child, parent in parents.items():
            if parent in found and child not in found:
                found.add(child)
                grew = True
    return sorted(found)


@dataclass(frozen=True, slots=True)
class RuleTerms:
    """The rule's settings, as saved or as previewed."""

    enabled: bool
    days: int
    product_type_ids: list[uuid.UUID]
    action: OverdueAction
    state_id: uuid.UUID | None


async def _overdue(session: AsyncSession, terms: RuleTerms, now: datetime) -> Select[Asset]:
    """The live assets the rule acts on now (scanned before, too long ago, not disposed)."""
    statement = (
        select(Asset)
        .join(AssetState, AssetState.id == Asset.state_id)
        .where(
            Asset.deleted_at.is_(None),
            Asset.last_scanned_at.is_not(None),
            Asset.last_scanned_at < now - timedelta(days=terms.days),
            AssetState.category != AssetStateCategory.DISPOSED,
        )
    )
    if terms.product_type_ids:
        types = await _type_tree(session, terms.product_type_ids)
        statement = statement.where(Asset.product_type_id.in_(types))
    if terms.action is OverdueAction.MOVE_STATE and terms.state_id is not None:
        already: ColumnElement[bool] = Asset.state_id != terms.state_id
        statement = statement.where(already)
    return statement


async def _reachable(session: AsyncSession, type_ids: Sequence[uuid.UUID]) -> set[uuid.UUID]:
    """States some life cycle of these product types (all life cycles when none) moves into."""
    if type_ids:
        cycles = {
            c
            for t in await _type_tree(session, type_ids)
            if (c := await _life_cycle_id(session, t)) is not None
        }
    else:
        cycles = set(
            await session.scalars(
                select(AssetLifeCycle.id).where(AssetLifeCycle.deleted_at.is_(None))
            )
        )
    if not cycles:
        return set()
    return set(
        await session.scalars(
            select(AssetLifeCycleTransition.to_state_id).where(
                AssetLifeCycleTransition.life_cycle_id.in_(cycles)
            )
        )
    )


async def target_states(
    session: AsyncSession, subject: Subject, type_ids: Sequence[uuid.UUID]
) -> list[uuid.UUID]:
    """The states the rule may move these product types' assets to (the settings' choices)."""
    require_configure(subject)
    disposed = set(
        await session.scalars(
            select(AssetState.id).where(AssetState.category == AssetStateCategory.DISPOSED)
        )
    )
    return sorted((await _reachable(session, type_ids)) - disposed)


async def _terms(
    session: AsyncSession, values: Mapping[str, Any], row: AssetOverdueRule
) -> RuleTerms:
    merged = {name: values.get(name, getattr(row, name)) for name in RULE_FIELDS}
    try:
        action = OverdueAction(str(merged["action"]))
    except ValueError:
        _refuse([Problem("action", "invalid_choice")])
    types = [uuid.UUID(str(t)) for t in dict.fromkeys(merged["product_type_ids"] or [])]
    state = None if merged["state_id"] is None else uuid.UUID(str(merged["state_id"]))
    days = merged["days"]
    problems = [
        Problem(f, c)
        for f, c in rule_problems(
            enabled=bool(merged["enabled"]),
            days=days if isinstance(days, int) else 0,
            action=action,
            state_id=state,
        )
    ]
    if state is not None:
        found = await session.get(AssetState, state)
        if found is None or found.deleted_at is not None:
            problems.append(Problem("state_id", "asset_state_not_found"))
        elif found.category == AssetStateCategory.DISPOSED:
            problems.append(Problem("state_id", "value_not_allowed"))
        elif action is OverdueAction.MOVE_STATE and state not in await _reachable(session, types):
            # No life cycle of these types moves an asset there: never forced (the coordinator).
            problems.append(Problem("state_id", "asset_overdue_state_unreachable"))
    if types:
        known = set(
            await session.scalars(
                select(AssetProductType.id).where(
                    AssetProductType.id.in_(types), AssetProductType.deleted_at.is_(None)
                )
            )
        )
        if set(types) - known:
            problems.append(Problem("product_type_ids", "asset_product_type_not_found"))
    _refuse(problems)
    return RuleTerms(
        enabled=bool(merged["enabled"]),
        days=int(days),
        product_type_ids=types,
        action=action,
        state_id=state,
    )


async def preview(session: AsyncSession, subject: Subject, values: Mapping[str, Any]) -> int:
    """How many of the tenant's assets the rule, as sent, would act on now (AC2)."""
    require_configure(subject)
    # Read-only (it is not audited, tests/test_audit_routes.py): the stored rule or its defaults,
    # never created here.
    terms = await _terms(session, values, await _stored_rule(session))
    found = await session.scalar(
        select(func.count()).select_from(
            (await _overdue(session, terms, system_clock.now())).subquery()
        )
    )
    return int(found or 0)


def _json(value: object) -> Any:  # noqa: ANN401 - history stores JSON values
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list):
        return [_json(v) for v in value]
    return value


async def save_rule(
    session: AsyncSession,
    subject: Subject,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> AssetOverdueRule:
    """Change the rule (If-Match), with its history and event."""
    require_configure(subject)
    await get_rule(session)
    row = await session.scalar(select(AssetOverdueRule).with_for_update())
    assert row is not None  # noqa: S101 - get_rule made it
    await _fresh(session, row, expected_version, RULE_RECORD_TYPE)
    terms = await _terms(session, values, row)
    wanted = {
        "enabled": terms.enabled,
        "days": terms.days,
        "product_type_ids": terms.product_type_ids,
        "action": terms.action.value,
        "state_id": terms.state_id,
    }
    changes = [
        Change(k, _json(getattr(row, k)), _json(v))
        for k, v in wanted.items()
        if k in values and getattr(row, k) != v
    ]
    if not changes:
        return row
    for change in changes:
        setattr(row, change.field, wanted[change.field])
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await record_changes(
        session,
        record_type=RULE_RECORD_TYPE,
        record_id=SETTINGS_RECORD,  # one rule per tenant, as the settings (stale_version reads it)
        version=row.version,
        kind="updated",
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        OverdueRuleChanged(action="updated"),
        aggregate_id=row.tenant_id,
        aggregate_version=row.version,
    )
    return row


async def list_runs(session: AsyncSession, subject: Subject) -> list[AssetOverdueRun]:
    """The rule's latest runs (each lists what it changed), newest first."""
    require_configure(subject)
    return list(
        await session.scalars(
            select(AssetOverdueRun).order_by(AssetOverdueRun.ran_at.desc()).limit(RUNS_LISTED)
        )
    )


async def _act(session: AsyncSession, row: Asset, terms: RuleTerms) -> dict[str, str | None]:
    """Move one asset as the rule says, as the system (source `rule`), its history naming it."""
    before_state = row.state_id
    if terms.action is OverdueAction.TRASH:
        row.deleted_at = datetime.now(UTC)
        await _saved(
            session, None, row, [Change("deleted", old=False, new=True)],
            action="deleted", source="rule",
        )  # fmt: skip
        return {"asset_id": str(row.id), "action": "trash", "from_state_id": str(before_state)}
    assert terms.state_id is not None  # noqa: S101 - rule_problems refused it otherwise
    move = {m.to_state_id: m for m in await _moves(session, row)}.get(terms.state_id)
    why = (
        "transition_not_allowed"
        if move is None
        else "permission_required"
        if move.permission is not None
        else "fields_required"
        if _missing(row, tuple(move.required_fields or ()))
        else None
    )
    if why is not None:  # its own state has no move there it may make: skipped, never forced
        return {
            "asset_id": str(row.id),
            "action": "skipped",
            "reason": why,
            "from_state_id": str(before_state),
        }
    target = await session.get(AssetState, terms.state_id)
    before = await session.get(AssetState, before_state)
    kind = await session.get(AssetProductType, row.product_type_id)
    assert target is not None  # noqa: S101 - checked when saved; a foreign key holds the rest
    assert before is not None  # noqa: S101
    assert kind is not None  # noqa: S101
    if not counts_toward_limit(kind.category, kind.kind, before.category) and counts_toward_limit(
        kind.category, kind.kind, target.category
    ):
        await _reserve(session)
    row.state_id = target.id
    await _saved(
        session, None, row, [Change("state_id", str(before_state), str(target.id))],
        action="updated", source="rule",
    )  # fmt: skip
    return {
        "asset_id": str(row.id),
        "action": "move_state",
        "from_state_id": str(before_state),
        "to_state_id": str(target.id),
    }


async def _skipped_last_time(session: AsyncSession) -> set[str | None]:
    last = await session.scalar(
        select(AssetOverdueRun).order_by(AssetOverdueRun.ran_at.desc()).limit(1)
    )
    if last is None:
        return set()
    return {c.get("asset_id") for c in last.changed if c.get("action") == "skipped"}


async def run_rule(session: AsyncSession, *, now: datetime | None = None) -> AssetOverdueRun | None:
    """One run for the session's tenant: act on what is overdue now; the run lists it (AC1)."""
    rule = await session.scalar(select(AssetOverdueRule).with_for_update(skip_locked=True))
    if rule is None or not rule.enabled:
        return None
    terms = RuleTerms(
        enabled=True,
        days=rule.days,
        product_type_ids=list(rule.product_type_ids),
        action=OverdueAction(rule.action),
        state_id=rule.state_id,
    )
    if terms.action is OverdueAction.MOVE_STATE and terms.state_id is None:
        return None
    at = now or system_clock.now()
    statement = (await _overdue(session, terms, at)).order_by(Asset.id).limit(RUN_LIST_MAX)
    # The rule is the reason a "reason required" state asks for (accepted by the coordinator):
    # a labelled code with its parameters in the history's automation_ref, never free text.
    ref = {
        "kind": "asset_overdue_rule",
        "action": rule.action,
        "reason": OVERDUE_REASON,
        "params": {"days": rule.days},
    }
    changed: list[dict[str, str | None]] = []
    for row in list(await session.scalars(statement.with_for_update(of=Asset, skip_locked=True))):
        try:
            async with session.begin_nested():
                with automated(session, ref):
                    changed.append(await _act(session, row, terms))
        except AppError as error:  # e.g. the plan's asset limit: left for the next run
            log.warning("asset_overdue_skipped", asset_id=str(row.id), code=error.code)
    applied = [c for c in changed if c["action"] != "skipped"]
    skipped = {c["asset_id"] for c in changed if c["action"] == "skipped"}
    if not applied and skipped <= await _skipped_last_time(session):
        return None  # nothing new: an asset skipped before is not listed again every hour
    run = AssetOverdueRun(
        id=new_id(),
        tenant_id=rule.tenant_id,
        ran_at=at,
        days=rule.days,
        action=rule.action,
        state_id=rule.state_id,
        changed_count=len(applied),
        changed=changed,
    )
    session.add(run)
    await session.flush()
    await record(
        session,
        action_code="asset_overdue_rule.ran",
        facts=WORKER,
        actor=(AuditActorType.AUTOMATION, None),
        object_type="asset_overdue_run",
        object_id=run.id,
        details={
            "changed": len(applied),
            "skipped": len(skipped),
            "action": rule.action,
            "days": rule.days,
        },
    )
    await record_event(
        session,
        OverdueRuleChanged(action="ran", run_id=run.id, changed_count=len(applied)),
        aggregate_id=run.id,
    )
    return run


async def overdue_sweep(database: Database, settings: Settings) -> None:
    """Each tenant's overdue-scan rule run (RLS: app.tenant_id set), like the valuation sweep."""
    del settings
    for tenant in await _tenants(database):
        async with database.tenant_session(TenantContext(tenant)) as session:
            run = await run_rule(session)
        if run is not None:
            log.info("asset_overdue_rule_ran", tenant_id=str(tenant), changed=run.changed_count)
