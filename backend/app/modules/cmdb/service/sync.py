"""Sync rules from assets and their runs (WP-053 S4a; REQ-CMDB-015, with 016's sources).

- **Who makes a rule (lane C's condition 1):** only someone who sees every asset and every CI:
  `cmdb.configure`, `cmdb.view` and `assets.view` each at scope "all" with no condition, and no
  fine-grained access rule narrowing them (ADR-053). Anyone else is refused
  (`cmdb_sync_author_restricted`), so a rule can never reach beyond what its author could.
- **The field map (lane C's condition 3):** CI attribute ← asset field, only fields assets marks
  syncable (assets' `syncable_fields`: never money, people, sealed or rule-restricted ones), and
  for custom targets only plain text fields of the target type that are neither personal nor
  sensitive. Anything else is 422.
- **The preview runs as the author (condition 2):** the assets and CIs it lists and counts are
  those the author may read; nothing is written.
- **A run writes as the sync identity (condition 4):** through the CI service's own save path
  (`cis.sync_create` / `sync_update`): its checks, metadata's custom rules, field history (source
  `asset_sync`, the run as the batch ID and the rule in the automation reference, each attribute
  stamped `asset_sync`), versions and outbox events. It is never narrowed by a reader's rules
  (the coordinator's condition 1). One audit entry per run: the rule, its trigger and counts,
  actor "automation".
- **Who wins (REQ-CMDB-016):** a changed asset value replaces the CI's value only where the
  asset sync's source wins (domain/sources.py); elsewhere the attribute is `kept`.
- **Reading runs (condition 5, the coordinator's condition 1):** `cmdb.configure` only. A reader
  who sees every CI and asset (unrestricted `cmdb.view` and `assets.view`) gets the totals and
  every item; anyone narrower gets no totals (they count CIs outside their reach) and only the
  items whose CI and asset they may see. Kept attributes are listed only where the reader may
  read the field (never a hidden, masked or sealed one, the coordinator's condition 6).
- **When:** on demand, hourly for each enabled rule, and incrementally when an asset changes:
  the consumer queues the asset's ID on the rule's next incremental run (IDs only); the run
  re-reads the asset through assets' interface.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import AppError, NotFound, PermissionDenied, ValidationFailed
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules import assets, metadata
from app.modules.audit import WORKER as WORKER_FACTS
from app.modules.audit import AuditActorType, record
from app.modules.cmdb.domain import field_access as field_rules
from app.modules.cmdb.domain import sources as source_rules
from app.modules.cmdb.domain import sync as domain
from app.modules.cmdb.domain.types import Problem
from app.modules.cmdb.events import SyncRuleChanged, SyncRunChanged
from app.modules.cmdb.infra.models import Ci, SyncRule, SyncRun
from app.modules.cmdb.service import cis
from app.modules.cmdb.service.catalogue import (
    CONFIGURE,
    VIEW,
    ensure_defaults,
    get_settings,
    get_state,
    get_type,
    invalid,
    require_configure,
    tenant_of,
)
from app.modules.identity_access import Subject, unrestricted
from app.shared.clock import system_clock
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Source, automated, in_batch, stale_version

log = get_logger(__name__)

ASSETS_VIEW = "assets.view"
RULE_RECORD = "cmdb_sync_rule"
RUN_RECORD = "cmdb_sync_run"
AUTOMATION_KIND = "cmdb_sync"  # the history's automation reference (labelled)
AUTHOR_RESTRICTED = "cmdb_sync_author_restricted"
RULE_NOT_FOUND = "cmdb_sync_rule_not_found"
RUN_NOT_FOUND = "cmdb_sync_run_not_found"
RUN_ACTION = "cmdb.sync_run_finished"
BATCH = 200  # assets per transaction
FULL_EVERY = timedelta(hours=1)
INCREMENTAL_MAX = 1000  # assets one incremental run collects; more and it reads every match
PREVIEW_SCAN = 5000  # assets a preview counts at most
PREVIEW_ITEMS = 50
TEXT_KINDS = frozenset({metadata.FieldType.TEXT, metadata.FieldType.LONG_TEXT})
_HISTORY_SOURCE: Source = "asset_sync"  # the run is the batch, the rule the automation ref


class SyncRuleRepository(Repository[SyncRule]):
    """Sync rules of the session's tenant."""

    model = SyncRule


@dataclass(frozen=True)
class RuleInput:
    """A rule as sent (create, change and preview)."""

    name: str
    target_type_id: uuid.UUID
    field_map: Mapping[str, str]
    filter: Any = None
    target_state_id: uuid.UUID | None = None
    enabled: bool = False


def _now() -> datetime:
    return system_clock.now()


def require_author(subject: Subject) -> None:
    """403 unless the person may make sync rules (lane C's condition 1)."""
    require_configure(subject)
    if not all(unrestricted(subject, p) for p in (CONFIGURE, VIEW, ASSETS_VIEW)):
        raise PermissionDenied(code=AUTHOR_RESTRICTED, params={"permission": CONFIGURE})


async def custom_targets(
    session: AsyncSession, type_id: uuid.UUID
) -> dict[str, domain.SyncValueKind]:
    """The target type's custom fields a rule may fill.

    Live plain text only, never personal or sensitive (ADR-047, ADR-050).
    """
    definitions = await metadata.definitions(session, cis.ENTITY, type_id=type_id)
    return {
        m.key: domain.SyncValueKind.TEXT
        for m in await metadata.field_marks(session, cis.ENTITY, type_id=type_id)
        if not m.personal_data
        and not m.sensitive
        and m.seal_state == metadata.PLAIN
        and (d := definitions.get(m.key)) is not None
        and d.type in TEXT_KINDS
        and not d.retired
    }


def _asset_fields() -> dict[str, domain.SyncValueKind]:
    return {k: domain.SyncValueKind(v.value) for k, v in assets.syncable_fields().items()}


@dataclass(frozen=True)
class Mappable:
    """What a rule may map: syncable asset fields, CI attributes, and the filter's fields."""

    asset_fields: dict[str, domain.SyncValueKind]
    ci_attributes: dict[str, domain.SyncValueKind]
    filter_fields: tuple[str, ...]


async def mappable(session: AsyncSession, type_id: uuid.UUID | None) -> Mappable:
    """For the rule editor; `type_id` adds that type's custom text fields."""
    custom = await custom_targets(session, type_id) if type_id is not None else {}
    return Mappable(
        asset_fields=_asset_fields(),
        ci_attributes={
            **domain.CI_TARGETS,
            **{f"{domain.CUSTOM}{k}": v for k, v in sorted(custom.items())},
        },
        filter_fields=assets.sync_filter_fields(),
    )


async def _checked(session: AsyncSession, data: RuleInput) -> None:
    problems: list[Problem] = []
    name = data.name.strip()
    if not name or len(name) > domain.NAME_MAX:
        problems.append(Problem("name", "invalid_value"))
    await get_type(session, data.target_type_id)
    if data.target_state_id is not None:
        await get_state(session, data.target_state_id)
    assets.check_sync_filter(data.filter)
    problems += domain.field_map_problems(
        data.field_map, _asset_fields(), await custom_targets(session, data.target_type_id)
    )
    if problems:
        raise invalid(problems)


async def _name_taken(session: AsyncSession, name: str, other: uuid.UUID | None) -> None:
    clash = select(SyncRule.id).where(
        func.lower(SyncRule.name) == name.lower(), SyncRule.deleted_at.is_(None)
    )
    if other is not None:
        clash = clash.where(SyncRule.id != other)
    if await session.scalar(clash) is not None:
        raise invalid([Problem("name", "duplicate")])


async def _rule_event(session: AsyncSession, row: SyncRule, action: str, fields: list[str]) -> None:
    await record_event(
        session,
        SyncRuleChanged(rule_id=row.id, action=action, changed_fields=fields),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


# --- rules ----------------------------------------------------------------------------------------


async def list_rules(session: AsyncSession, subject: Subject) -> list[SyncRule]:
    """Every live rule (`cmdb.configure`)."""
    require_configure(subject)
    return list(
        await session.scalars(
            select(SyncRule)
            .where(SyncRule.deleted_at.is_(None))
            .order_by(func.lower(SyncRule.name), SyncRule.id)
        )
    )


async def _live(session: AsyncSession, rule_id: uuid.UUID) -> SyncRule:
    row: SyncRule | None = await session.scalar(
        select(SyncRule).where(SyncRule.id == rule_id, SyncRule.deleted_at.is_(None))
    )
    if row is None:
        raise NotFound(code=RULE_NOT_FOUND)
    return row


async def get_rule(session: AsyncSession, subject: Subject, rule_id: uuid.UUID) -> SyncRule:
    """One live rule (`cmdb.configure`)."""
    require_configure(subject)
    return await _live(session, rule_id)


def _columns(data: RuleInput) -> dict[str, Any]:
    return {
        "name": data.name.strip(),
        "filter": data.filter,
        "target_type_id": data.target_type_id,
        "target_state_id": data.target_state_id,
        "field_map": dict(sorted(data.field_map.items())),
        "enabled": data.enabled,
    }


async def create_rule(session: AsyncSession, subject: Subject, data: RuleInput) -> SyncRule:
    """A new rule (lane C's condition 1 and 3); off until switched on, unless sent on."""
    require_author(subject)
    await ensure_defaults(session)
    await _checked(session, data)
    await _name_taken(session, data.name.strip(), None)
    row = SyncRule(source_kind=domain.SyncSourceKind.ASSETS.value, **_columns(data))
    await SyncRuleRepository(session).add(row)
    await _rule_event(session, row, "created", sorted(_columns(data)))
    return row


async def update_rule(
    session: AsyncSession,
    subject: Subject,
    rule_id: uuid.UUID,
    data: RuleInput,
    *,
    expected_version: int,
) -> tuple[SyncRule, list[str]]:
    """Change a rule (If-Match). Returns it and the names of the fields that changed."""
    require_author(subject)
    row = await _live(session, rule_id)
    if row.version != expected_version:
        raise await stale_version(session, row, expected_version=expected_version)
    await _checked(session, data)
    await _name_taken(session, data.name.strip(), row.id)
    changes = {k: v for k, v in _columns(data).items() if getattr(row, k) != v}
    if not changes:
        return row, []
    updated = await SyncRuleRepository(session).update(
        row.id, expected_version=expected_version, changes=changes
    )
    await _rule_event(session, updated, "updated", sorted(changes))
    return updated, sorted(changes)


async def delete_rule(
    session: AsyncSession, subject: Subject, rule_id: uuid.UUID, *, expected_version: int
) -> None:
    """Remove a rule (soft delete); its runs stay. A run in progress finishes its batch."""
    require_author(subject)
    row = await _live(session, rule_id)
    deleted = await SyncRuleRepository(session).soft_delete(
        row.id, expected_version=expected_version
    )
    await _rule_event(session, deleted, "deleted", [])


# --- preview (as the author, lane C's condition 2) ------------------------------------------------


@dataclass(frozen=True)
class PreviewItem:
    """What a rule would do with one asset (IDs the author may see)."""

    asset_id: uuid.UUID
    asset_tag: str | None
    asset_name: str | None
    ci_id: uuid.UUID | None
    outcome: domain.SyncOutcome
    changes: tuple[str, ...]
    kept: tuple[str, ...]


@dataclass(frozen=True)
class Preview:
    """Counts first (over at most PREVIEW_SCAN assets: `complete` says whether that was all)."""

    total: int
    complete: bool
    counts: dict[str, int]
    items: list[PreviewItem]


def _outcome_of(
    precedence: source_rules.Precedence, record: Ci | None, values: Mapping[str, Any]
) -> tuple[domain.SyncOutcome, tuple[str, ...], tuple[str, ...]]:
    if record is None:
        return domain.SyncOutcome.CREATED, tuple(sorted(k for k, v in values.items() if v)), ()
    current = field_rules.flat(cis.snapshot(record))
    found = domain.plan(precedence, current, cis.effective_stamps(record), _json_values(values))
    return found.outcome, tuple(sorted(found.changes)), found.kept


def _json_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """Asset values as the CI snapshot holds them (IDs as text), to compare like with like."""
    return {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in values.items()}


def _typed(values: Mapping[str, Any]) -> dict[str, Any]:
    """Snapshot-form values back as the CI's columns take them (IDs as UUIDs)."""
    out: dict[str, Any] = {}
    for key, value in values.items():
        kind = domain.CI_TARGETS.get(key)
        if kind in (domain.SyncValueKind.SITE, domain.SyncValueKind.GROUP) and value is not None:
            out[key] = uuid.UUID(str(value))
        else:
            out[key] = value
    return out


async def preview(session: AsyncSession, subject: Subject, data: RuleInput) -> Preview:
    """What the rule would do now, read as the author; nothing is written."""
    require_author(subject)
    await ensure_defaults(session)
    await _checked(session, data)
    precedence = source_rules.precedence_of((await get_settings(session)).source_precedence)
    total = await assets.sync_count(session, subject, data.filter)
    counts = {o.value: 0 for o in domain.SyncOutcome}
    items: list[PreviewItem] = []
    scanned, after = 0, None
    while scanned < PREVIEW_SCAN:
        page = await assets.sync_page(
            session, subject, data.filter, after=after, limit=min(BATCH, PREVIEW_SCAN - scanned)
        )
        if not page:
            break
        linked = {
            r.asset_id: r
            for r in await session.scalars(
                cis.visible_rows(subject).where(Ci.asset_id.in_([a.id for a in page]))
            )
        }
        for asset in page:
            values = domain.mapped(data.field_map, asset.values)
            outcome, changes, kept = _outcome_of(precedence, linked.get(asset.id), values)
            counts[outcome.value] += 1
            if len(items) < PREVIEW_ITEMS:
                record_ = linked.get(asset.id)
                items.append(
                    PreviewItem(
                        asset.id,
                        asset.tag,
                        asset.values.get("name"),
                        record_.id if record_ is not None else None,
                        outcome,
                        changes,
                        kept,
                    )
                )
        scanned += len(page)
        after = page[-1].id
    return Preview(total=total, complete=scanned >= total, counts=counts, items=items)


# --- runs: queueing -------------------------------------------------------------------------------


async def _run_event(session: AsyncSession, run: SyncRun) -> None:
    await record_event(
        session,
        SyncRunChanged(run_id=run.id, rule_id=run.rule_id, status=run.status),
        aggregate_id=run.id,
        aggregate_version=run.version,
    )


async def _open_run(
    session: AsyncSession, rule_id: uuid.UUID, *, incremental: bool, lock: bool = False
) -> SyncRun | None:
    rows = select(SyncRun).where(
        SyncRun.rule_id == rule_id,
        SyncRun.status == domain.SyncRunStatus.QUEUED.value,
        SyncRun.asset_ids.is_not(None) if incremental else SyncRun.asset_ids.is_(None),
    )
    if lock:
        rows = rows.with_for_update()
    found: SyncRun | None = await session.scalar(rows.order_by(SyncRun.created_at).limit(1))
    return found


async def queue_run(session: AsyncSession, subject: Subject, rule_id: uuid.UUID) -> SyncRun:
    """Run the rule now (a full run); one already queued is returned instead of a second."""
    require_author(subject)
    rule = await _live(session, rule_id)
    if (queued := await _open_run(session, rule.id, incremental=False)) is not None:
        return queued
    run = SyncRun(
        tenant_id=tenant_of(session), rule_id=rule.id, trigger=domain.SyncTrigger.MANUAL.value
    )
    session.add(run)
    await session.flush()
    await _run_event(session, run)
    return run


async def on_asset_changed(envelope: Any, session: AsyncSession | None) -> None:  # noqa: ANN401 - the event envelope
    """An asset changed: queue its ID on each enabled rule's next incremental run.

    IDs only (lane C's condition 5): the run re-reads the asset through assets' interface, and
    applies the rule's filter then. Idempotent: an ID already queued is not added twice; past
    INCREMENTAL_MAX IDs the run reads every match instead.
    """
    assert session is not None  # noqa: S101 - transactional consumer
    asset_id = str(uuid.UUID(str(envelope.payload["asset_id"])))
    rules = list(
        await session.scalars(
            select(SyncRule.id).where(SyncRule.enabled.is_(True), SyncRule.deleted_at.is_(None))
        )
    )
    for rule_id in rules:
        run = await _open_run(session, rule_id, incremental=True, lock=True)
        if run is None:
            run = SyncRun(
                tenant_id=tenant_of(session),
                rule_id=rule_id,
                trigger=domain.SyncTrigger.ASSET_CHANGED.value,
                asset_ids=[],
            )
            session.add(run)
        ids = list(run.asset_ids or [])
        if asset_id in ids:
            continue
        if len(ids) >= INCREMENTAL_MAX:
            if await _open_run(session, rule_id, incremental=False) is None:
                session.add(
                    SyncRun(
                        tenant_id=tenant_of(session),
                        rule_id=rule_id,
                        trigger=domain.SyncTrigger.SCHEDULE.value,
                    )
                )
            continue
        run.asset_ids = [*ids, asset_id]
    await session.flush()


# --- runs: the worker -----------------------------------------------------------------------------


@dataclass
class _Tally:
    counts: dict[str, int] = field(default_factory=lambda: {o.value: 0 for o in domain.SyncOutcome})
    outcomes: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        asset_id: uuid.UUID,
        ci_id: uuid.UUID | None,
        outcome: domain.SyncOutcome,
        *,
        kept: Sequence[str] = (),
        code: str | None = None,
    ) -> None:
        self.counts[outcome.value] += 1
        if len(self.outcomes) < domain.OUTCOMES_MAX and outcome is not domain.SyncOutcome.UNCHANGED:
            item: dict[str, Any] = {
                "asset_id": str(asset_id),
                "ci_id": str(ci_id) if ci_id else None,
                "outcome": outcome.value,
            }
            if kept:
                item["kept"] = list(kept)
            if code:
                item["code"] = code
            self.outcomes.append(item)


def _code(error: AppError) -> str:
    """A field code the run screen can label (`errors.field.<code>`)."""
    if isinstance(error, ValidationFailed) and error.errors:
        return error.errors[0].code
    return domain.ITEM_REFUSED


async def _apply(
    session: AsyncSession,
    rule: SyncRule,
    precedence: source_rules.Precedence,
    asset: assets.SyncedAsset,
    tally: _Tally,
) -> None:
    values = domain.mapped(rule.field_map, asset.values)
    record_ = await cis.ci_of_asset(session, asset.id)
    savepoint = await session.begin_nested()
    try:
        if record_ is None:
            if not values.get("name"):
                await savepoint.rollback()
                tally.add(asset.id, None, domain.SyncOutcome.FAILED, code=domain.NAME_REQUIRED)
                return
            core = {k: v for k, v in values.items() if not k.startswith(domain.CUSTOM)}
            custom = {
                k.removeprefix(domain.CUSTOM): v
                for k, v in values.items()
                if k.startswith(domain.CUSTOM) and v is not None
            }
            made = await cis.sync_create(
                session,
                {
                    **core,
                    "type_id": rule.target_type_id,
                    "state_id": rule.target_state_id,
                    "custom": custom or None,
                },
                asset_id=asset.id,
                source=_HISTORY_SOURCE,
            )
            await savepoint.commit()
            tally.add(asset.id, made.id, domain.SyncOutcome.CREATED)
            return
        current = field_rules.flat(cis.snapshot(record_))
        found = domain.plan(
            precedence, current, cis.effective_stamps(record_), _json_values(values)
        )
        if found.changes:
            await cis.sync_update(session, record_, _typed(found.changes), source=_HISTORY_SOURCE)
        await savepoint.commit()
        tally.add(asset.id, record_.id, found.outcome, kept=found.kept)
    except AppError as refused:
        await savepoint.rollback()
        tally.add(
            asset.id,
            record_.id if record_ is not None else None,
            domain.SyncOutcome.FAILED,
            code=_code(refused),
        )


async def _claim(database: Database, tenant: uuid.UUID) -> uuid.UUID | None:
    """The oldest queued run of a live, enabled rule, now `running` (or None)."""
    async with database.tenant_session(TenantContext(tenant)) as session:
        run: SyncRun | None = await session.scalar(
            select(SyncRun)
            .where(
                SyncRun.status == domain.SyncRunStatus.QUEUED.value,
                exists().where(
                    SyncRule.id == SyncRun.rule_id,
                    SyncRule.deleted_at.is_(None),
                    SyncRule.enabled.is_(True) | (SyncRun.trigger == "manual"),
                ),
            )
            .order_by(SyncRun.created_at, SyncRun.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if run is None:
            return None
        run.status = domain.SyncRunStatus.RUNNING.value
        run.started_at = _now()
        run.version += 1
        await session.flush()
        await _run_event(session, run)
        return run.id


async def _batches(
    session: AsyncSession, rule: SyncRule, run: SyncRun, after: uuid.UUID | None
) -> list[assets.SyncedAsset]:
    if run.asset_ids is not None:
        if after is not None:
            return []
        return await assets.sync_assets(session, rule.filter, [uuid.UUID(i) for i in run.asset_ids])
    return await assets.sync_page(session, None, rule.filter, after=after, limit=BATCH)


async def _process(database: Database, tenant: uuid.UUID, run_id: uuid.UUID) -> None:
    """One run, a transaction per batch of assets; the counts are saved with each batch."""
    tally = _Tally()
    after: uuid.UUID | None = None
    while True:
        async with database.tenant_session(TenantContext(tenant)) as session:
            run = await session.get(SyncRun, run_id)
            rule = await session.get(SyncRule, run.rule_id) if run is not None else None
            if run is None or rule is None:  # pragma: no cover - runs are never deleted
                return
            if rule.deleted_at is not None:
                break
            precedence = source_rules.precedence_of((await get_settings(session)).source_precedence)
            page = await _batches(session, rule, run, after)
            if not page:
                break
            in_batch(session, run.id)
            ref = {
                "kind": AUTOMATION_KIND,
                "id": str(rule.id),
                "run_id": str(run.id),
            }
            with automated(session, ref):
                for asset in page:
                    await _apply(session, rule, precedence, asset, tally)
            in_batch(session, None)
            _save_tally(run, tally)
            await session.flush()
            after = page[-1].id
            if run.asset_ids is not None:
                break
    await _finish(database, tenant, run_id, tally, failure=None)


def _save_tally(run: SyncRun, tally: _Tally) -> None:
    run.created_count = tally.counts[domain.SyncOutcome.CREATED.value]
    run.updated_count = tally.counts[domain.SyncOutcome.UPDATED.value]
    run.kept_count = tally.counts[domain.SyncOutcome.KEPT.value]
    run.unchanged_count = tally.counts[domain.SyncOutcome.UNCHANGED.value]
    run.failed_count = tally.counts[domain.SyncOutcome.FAILED.value]
    run.outcomes = list(tally.outcomes)


async def _finish(
    database: Database,
    tenant: uuid.UUID,
    run_id: uuid.UUID,
    tally: _Tally,
    *,
    failure: str | None,
) -> None:
    async with database.tenant_session(TenantContext(tenant)) as session:
        run = await session.get(SyncRun, run_id)
        if run is None:  # pragma: no cover - runs are never deleted
            return
        if failure is None:
            _save_tally(run, tally)
        run.status = (
            domain.SyncRunStatus.FAILED.value if failure else domain.SyncRunStatus.SUCCEEDED.value
        )
        run.failure = failure
        run.ended_at = _now()
        run.version += 1
        await session.flush()
        await _run_event(session, run)
        # One entry per run (lane C's condition 4): the rule, the trigger and the counts.
        await record(
            session,
            action_code=RUN_ACTION,
            facts=WORKER_FACTS,
            object_type=RUN_RECORD,
            object_id=run.id,
            actor=(AuditActorType.AUTOMATION, None),
            details={
                "rule_id": str(run.rule_id),
                "trigger": run.trigger,
                "status": run.status,
                "created": run.created_count,
                "updated": run.updated_count,
                "kept": run.kept_count,
                "unchanged": run.unchanged_count,
                "failed": run.failed_count,
                **({"failure": failure} if failure else {}),
            },
        )


async def _queue_due(database: Database, tenant: uuid.UUID) -> None:
    """An hourly full run for each enabled rule whose last full run is over an hour old."""
    async with database.tenant_session(TenantContext(tenant)) as session:
        rules = list(
            await session.scalars(
                select(SyncRule).where(SyncRule.enabled.is_(True), SyncRule.deleted_at.is_(None))
            )
        )
        due = _now() - FULL_EVERY
        for rule in rules:
            last = await session.scalar(
                select(func.max(SyncRun.created_at)).where(
                    SyncRun.rule_id == rule.id, SyncRun.asset_ids.is_(None)
                )
            )
            if last is None or last < due:
                run = SyncRun(
                    tenant_id=tenant,
                    rule_id=rule.id,
                    trigger=domain.SyncTrigger.SCHEDULE.value,
                )
                session.add(run)
                await session.flush()
                await _run_event(session, run)


async def run_tenant(database: Database, tenant: uuid.UUID) -> None:
    """One tenant: queue its due runs, then work through its queued ones in order."""
    await _queue_due(database, tenant)
    while (run_id := await _claim(database, tenant)) is not None:
        try:
            await _process(database, tenant, run_id)
        except Exception:  # one broken run must not stop the others; it is logged
            log.exception("cmdb_sync_run_failed", run_id=str(run_id))
            await _finish(database, tenant, run_id, _Tally(), failure="unexpected")


async def run_sync_rules(database: Database, settings: Settings) -> None:
    """Schedule: every tenant's due and queued sync runs."""
    del settings
    async with database.platform_session() as session:
        tenants = list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        try:
            await run_tenant(database, tenant)
        except Exception:  # pragma: no cover - one tenant's failure must not stop the others
            log.exception("cmdb_sync_tenant_failed", tenant_id=str(tenant))


# --- runs: reading (lane C's condition 5) ---------------------------------------------------------


async def list_runs(
    session: AsyncSession, subject: Subject, rule_id: uuid.UUID, *, limit: int = 20
) -> list[SyncRun]:
    """A rule's latest runs, newest first (`cmdb.configure`)."""
    require_configure(subject)
    await _live(session, rule_id)
    return list(
        await session.scalars(
            select(SyncRun)
            .where(SyncRun.rule_id == rule_id)
            .order_by(SyncRun.created_at.desc(), SyncRun.id.desc())
            .limit(max(1, min(limit, 100)))
        )
    )


@dataclass(frozen=True)
class OutcomeView:
    """One item of a run as this reader may see it: never an ID or a name they may not see."""

    outcome: str
    asset_id: uuid.UUID | None
    asset_label: str | None
    asset_restricted: bool
    ci_id: uuid.UUID | None
    ci_label: str | None
    ci_restricted: bool
    kept: tuple[str, ...]
    code: str | None


def sees_everything(subject: Subject) -> bool:
    """Whether a reader may see a run's totals: every CI and every asset is in their reach."""
    return unrestricted(subject, VIEW) and unrestricted(subject, ASSETS_VIEW)


async def get_run(
    session: AsyncSession, subject: Subject, run_id: uuid.UUID
) -> tuple[SyncRun, list[OutcomeView]]:
    """A run and its item outcomes through the reader's view (`cmdb.configure`).

    A narrower reader gets only the items whose CI and asset they may see (the caller hides
    the totals, `sees_everything`).
    """
    require_configure(subject)
    everything = sees_everything(subject)
    run: SyncRun | None = await session.scalar(select(SyncRun).where(SyncRun.id == run_id))
    if run is None:
        raise NotFound(code=RUN_NOT_FOUND)
    items = list(run.outcomes or [])
    asset_ids = [uuid.UUID(i["asset_id"]) for i in items if i.get("asset_id")]
    ci_ids = [uuid.UUID(i["ci_id"]) for i in items if i.get("ci_id")]
    refs = await assets.asset_refs(session, subject, asset_ids) if asset_ids else {}
    seen = (
        {r.id: r for r in await session.scalars(cis.visible_rows(subject).where(Ci.id.in_(ci_ids)))}
        if ci_ids and subject.holds(VIEW)
        else {}
    )
    out_of_sight = await cis.withheld(session, subject)
    views: list[OutcomeView] = []
    for item in items:
        asset_id = uuid.UUID(item["asset_id"]) if item.get("asset_id") else None
        ref = refs.get(asset_id) if asset_id else None
        asset_seen = ref is not None and not ref.hidden and not ref.gone and ref.name is not None
        ci_id = uuid.UUID(item["ci_id"]) if item.get("ci_id") else None
        ci = seen.get(ci_id) if ci_id else None
        views.append(
            OutcomeView(
                outcome=str(item.get("outcome")),
                asset_id=asset_id if asset_seen else None,
                asset_label=(f"{ref.tag} {ref.name}" if ref.tag else ref.name)
                if asset_seen and ref is not None
                else None,
                asset_restricted=asset_id is not None and not asset_seen,
                ci_id=ci.id if ci is not None else None,
                ci_label=f"{ci.display_id} {ci.name}" if ci is not None else None,
                ci_restricted=ci_id is not None and ci is None,
                kept=tuple(k for k in item.get("kept", ()) if k not in out_of_sight)
                if ci is not None
                else (),
                code=item.get("code"),
            )
        )
    if not everything:
        views = [v for v in views if not v.ci_restricted and not v.asset_restricted]
    return run, views
