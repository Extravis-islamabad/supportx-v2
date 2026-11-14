"""The person erasure job (ADR-052 §3): steps 0-7 in order, each idempotent, each committed.

`run_erasure` runs an approved erasure from its recorded `step` to the end, one transaction per
step: the step's work and the move to the next step commit together, so a run that stops resumes
exactly where it stopped, and a step that ran is never run again. Every step is idempotent all
the same (a crash between Keycloak's answer and the commit repeats the call).

A refusal at the start (a hold, the last admin, a break-glass account, an invalid approval, no
mentions report, a missing port) fails the erasure for good, audited with its code. Any other
failure (Keycloak or the session store down, an unexpected error) rolls the step back, records
the attempt and a code (never a message: it could hold data), and the schedule retries with
backoff; after MAX_ATTEMPTS the erasure is failed and audited. `failed` stays open: the person
may be half-erased, so no new erasure can start, and nothing ever exposes them half-erased
(the freeze comes first).

The schedule `identity_access__person_erasures` (every 30 s, every tenant) expires requests past
7 days, builds the mentions report of requested erasures (S1b, service/erasure_mentions.py) and
runs what is approved or running, honouring the backoff. A schedule rather than an
event consumer: it needs a database per step, and it also picks up a run a crashed worker left.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import Conflict
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.audit import WORKER, AuditActorType, AuditOutcome, erase_subject, record
from app.modules.identity_access.domain import erasure as rules
from app.modules.identity_access.domain.erasure import ErasureState, Step
from app.modules.identity_access.events import (
    KeycloakSessionEndPending,
    PersonErasureChanged,
    PersonErasureCompleted,
    UserStatusChanged,
    UserUpdated,
)
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdmin,
    IdentityAdminNotConfigured,
    IdentityAdminRefused,
    IdentityAdminUnavailable,
    KeycloakAdmin,
)
from app.modules.identity_access.infra.models import Invitation, PersonErasure, User
from app.modules.identity_access.service.directory import USER_RECORD_TYPE
from app.modules.identity_access.service.erasure import expire_due, refusal
from app.modules.identity_access.service.erasure_mentions import (
    build_report_batch,
    report_complete,
    reports_due,
)
from app.modules.identity_access.service.people import save_marks
from app.modules.identity_access.service.person_data import (
    ErasureStepFailed,
    missing_ports,
    registered_ports,
)
from app.modules.identity_access.service.person_data_ports import (
    revoke_api_keys,
    revoke_invitations,
)
from app.modules.identity_access.service.sso import organization_of
from app.modules.identity_access.service.worker_sessions import (
    KeycloakSessionIds,
    SessionsUnavailable,
    TenantSessionEnder,
    worker_keycloak_sessions,
    worker_session_ender,
)
from app.shared.action_links import revoke_for_recipient
from app.shared.clock import Clock, system_clock
from app.shared.events import record_event
from app.shared.history import Change, record_changes
from app.shared.mail import forget_recipient

log = get_logger(__name__)

ForgetMail = Callable[[AsyncSession, str], Awaitable[int]]


@dataclass
class JobEffects:
    """What the job reaches outside the database (fakes in tests)."""

    identity_admin: IdentityAdmin | None = None
    end_sessions: TenantSessionEnder | None = None
    keycloak_sessions: KeycloakSessionIds | None = None
    forget_mail: ForgetMail = forget_recipient
    clock: Clock = system_clock


@dataclass(frozen=True)
class RunOutcome:
    """Where a run left the erasure."""

    state: str
    step: int
    error_code: str | None = None


# The count kinds the job itself records (each labelled `erasure_count.<kind>`; the ports declare
# theirs on the port).
JOB_KINDS: frozenset[str] = frozenset(
    {
        "action_links_revoked",
        "api_keys_revoked",
        "audit_personal_rows_removed",
        "files_kept",
        "invitations_revoked",
        "keycloak_accounts_deleted",
        "keycloak_memberships_removed",
        "keycloak_sessions_ending",
        "mail_messages_cleared",
        "person_fields_cleared",
        "profile_history_rows_erased",
        "sessions_ended",
        "successor_replaced",
    }
)


class StepRefused(Exception):
    """A start check failed: the erasure fails for good with this code."""

    def __init__(self, code: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = dict(details or {})


class StepUnavailable(Exception):
    """Something outside the database did not answer: rolled back, retried with backoff."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class _Run:
    session: AsyncSession
    row: PersonErasure
    person: User
    effects: JobEffects
    now: datetime
    counts: dict[str, int] = field(default_factory=dict)
    # Step 4 runs one port batch per transaction: where to go on (module, cursor) when it stays.
    stay: bool = False
    next_port: tuple[str | None, str | None] = (None, None)


CURSOR_MAX = 2000  # as the table's check


# --- the steps ------------------------------------------------------------------------------------


async def _recheck(run: _Run) -> None:
    """Step 0: the approval still holds and nothing stands in the way; pick the successor."""
    row, person = run.row, run.person
    if row.approved_by is None or row.approved_at is None or row.approved_by == row.requested_by:
        raise StepRefused(rules.APPROVAL_INVALID)
    if not report_complete(row.report):  # D-171 (a): never run on an incomplete report
        raise StepRefused(rules.REPORT_UNAVAILABLE)
    if person.id in {row.requested_by, row.approved_by}:
        raise StepRefused(rules.ERASE_SELF)
    # The approver vouches for the run and is the fallback successor: still active, not erased,
    # and still allowed to erase (lane C, #498), else the approval no longer stands.
    from app.modules.identity_access import subject_for  # noqa: PLC0415 - the package imports this

    approver = await run.session.get(User, row.approved_by)
    if (
        approver is None
        or approver.status != "active"
        or approver.deleted_at is not None
        or approver.erased_at is not None
        or not (await subject_for(run.session, row.tenant_id, approver.id)).holds(rules.ERASE_RIGHT)
    ):
        raise StepRefused(rules.APPROVAL_INVALID)
    code = await refusal(run.session, person, actor_id=row.approved_by)
    if code is not None:
        raise StepRefused(code)
    successor = await run.session.scalar(
        select(User.id).where(
            User.id == row.successor_id,
            User.status == "active",
            User.deleted_at.is_(None),
            User.erased_at.is_(None),
        )
    )
    # The requested successor left meanwhile: the approving admin takes over (lane C's review).
    row.effective_successor_id = successor or row.approved_by
    run.counts["successor_replaced"] = 0 if successor else 1


async def _freeze(run: _Run) -> None:
    """Step 1: no access of any kind from here on, before anything is removed."""
    session, person, effects = run.session, run.person, run.effects
    tenant = run.row.tenant_id
    if person.status != "disabled" or person.can_sign_in:
        await save_marks(
            session,
            person.id,
            expected_version=person.version,
            values={"status": "disabled", "can_sign_in": False},
            source="system",
        )
    # No session store in this worker (Valkey or the session cipher missing): the person's
    # sessions cannot be ended, so the step waits and retries, never skips (lane C, #498).
    if effects.end_sessions is None or effects.keycloak_sessions is None:
        raise StepUnavailable(rules.SESSIONS_UNAVAILABLE)
    try:
        keycloak_ids = await effects.keycloak_sessions(tenant, person.id)
        await effects.end_sessions(tenant, person.id)
    except SessionsUnavailable as exc:
        raise StepUnavailable(rules.SESSIONS_UNAVAILABLE) from exc
    # Their Keycloak sessions end in the background, through ADR-051's path (the consumer ends
    # each once Keycloak answers; the person's SupportX sessions are already ended above).
    for session_id in keycloak_ids:
        await record_event(
            session,
            KeycloakSessionEndPending(user_id=person.id, keycloak_session_id=session_id),
            aggregate_id=person.id,
        )
    run.counts["sessions_ended"] = 1
    run.counts["keycloak_sessions_ending"] = len(keycloak_ids)
    run.counts["api_keys_revoked"] = await revoke_api_keys(session, person.id, run.now)
    run.counts["invitations_revoked"] = await revoke_invitations(session, person.id, run.now)
    run.counts["action_links_revoked"] = await revoke_for_recipient(session, person.id)


async def _mail(run: _Run) -> None:
    """Step 2: their mail keeps no trace of them, while the address still finds it."""
    email = run.person.email
    run.counts["mail_messages_cleared"] = (
        await run.effects.forget_mail(run.session, email) if email else 0
    )


async def _keycloak_account(session: AsyncSession, person: User) -> str | None:
    if person.external_subject:
        return person.external_subject
    return await session.scalar(
        select(Invitation.keycloak_user_id)
        .where(Invitation.user_id == person.id, Invitation.keycloak_user_id.is_not(None))
        .order_by(Invitation.created_at.desc())
        .limit(1)
    )


async def _keycloak(run: _Run) -> None:
    """Step 3 (D5): out of this tenant's organisation; the account goes when no tenant has it."""
    account = await _keycloak_account(run.session, run.person)
    if account is None:  # never signed in, never invited: nothing in Keycloak
        run.counts["keycloak_memberships_removed"] = 0
        return
    admin = run.effects.identity_admin
    if admin is None:
        raise StepUnavailable(rules.IDENTITY_UNAVAILABLE)  # unreachable: retried, never skipped
    try:
        organization = await organization_of(run.session, admin)
        await admin.remove_member(organization.id, account)
        others = await admin.member_tenants(account)
        deleted = 0
        if not [tenant for tenant in others if tenant != str(run.row.tenant_id)]:
            await admin.delete_user(account)
            deleted = 1
    except (
        IdentityAdminUnavailable,
        IdentityAdminNotConfigured,
        IdentityAdminRefused,
        Conflict,  # the tenant's organisation is missing in Keycloak: a set-up to fix, retried
    ) as exc:
        raise StepUnavailable(rules.IDENTITY_UNAVAILABLE) from exc
    run.counts["keycloak_memberships_removed"] = 1
    run.counts["keycloak_accounts_deleted"] = deleted


async def _ports(run: _Run) -> None:
    """Step 4: one batch of one module's slice, in registry order (ADR-052 §4, batches).

    The job commits after each batch and calls again from the stored module and cursor, so a
    person with many records never needs one long transaction. When the last port is done, each
    kept file is audited with the admin's reason (once: it commits with the step's end).
    """
    row = run.row
    successor = row.effective_successor_id or row.approved_by
    if successor is None:  # step 0 always sets it; a hand-edited row is not run
        raise StepRefused(rules.APPROVAL_INVALID)
    keep = {uuid.UUID(file_id): reason for file_id, reason in row.keep_files.items()}
    ports = registered_ports()
    names = [port.module for port in ports]
    current = row.port_module or (names[0] if names else None)
    if current is not None:
        if current not in names:  # unregistered since the last batch: a release defect
            raise StepRefused(rules.PORT_MISSING, {"missing_ports": [current]})
        index = names.index(current)
        batch = await ports[index].erase_person(
            run.session,
            run.person.id,
            successor_id=successor,
            keep_files=keep,
            now=run.now,
            cursor=row.port_cursor if row.port_module == current else None,
        )
        undeclared = sorted(set(batch.counts) - set(ports[index].kinds))
        if undeclared:  # a release defect: its counts would show unlabelled (lane A's review)
            raise StepRefused(rules.PORT_KIND_UNDECLARED, {"port": current, "kinds": undeclared})
        for kind, count in batch.counts.items():
            run.counts[kind] = run.counts.get(kind, 0) + int(count)
        if batch.cursor is not None:
            if len(batch.cursor) > CURSOR_MAX:
                msg = "a port's cursor is too long"
                raise ValueError(msg)
            run.stay, run.next_port = True, (current, batch.cursor)
            return
        if index + 1 < len(names):
            run.stay, run.next_port = True, (names[index + 1], None)
            return
    for file_id, reason in sorted(keep.items(), key=lambda item: str(item[0])):
        await record(
            run.session,
            action_code="person.erasure_file_kept",
            facts=WORKER,
            object_type="file",
            object_id=file_id,
            details={"erasure_id": str(row.id), "person_id": str(row.person_id)},
            reason=reason,
            actor=(AuditActorType.SYSTEM, None),
        )
    run.counts["files_kept"] = len(keep)


# The person row after erasure (D6b): names from the code, nothing personal left.
_CLEARED = (
    "external_subject",
    "phone",
    "mobile",
    "job_title",
    "employee_id",
    "description",
    "signature",
    "manager_id",
    "time_zone",
    "nav_layout",
    "form_density",
    "ui_locale",
    "theme_mode",
    "text_scale",
    "week_start",
    "date_format",
    "time_format",
    "digits",
    "urdu_script",
    "request_visibility",
    "mfa_required_since",
    "mfa_enrolled_at",
    "invited_at",
    "directory_source",
    "last_login_at",
)


async def _person_row(run: _Run) -> None:
    """Step 5: the row stays (IDs everywhere point at it) with nothing personal in it."""
    person, row = run.person, run.row
    values: dict[str, Any] = dict.fromkeys(_CLEARED)
    code = rules.erased_code(person.id)
    values.update(
        first_name=rules.ERASED_PREFIX,
        last_name=code,
        display_name=rules.erased_name(person.id),
        name_custom=True,
        email=rules.erased_email(person.id),
        vip=False,
        status="disabled",
        can_sign_in=False,
        erased_at=run.now,
        erased_by=row.approved_by,
    )
    changed = sorted(name for name, value in values.items() if getattr(person, name) != value)
    new_version = person.version + 1
    await run.session.execute(
        update(User)
        .where(User.id == person.id)
        .values(**values, version=new_version, updated_at=run.now)
        .execution_options(synchronize_session=False)
    )
    # History names the fields only: the old values are what is being erased.
    await record_changes(
        run.session,
        record_type=USER_RECORD_TYPE,
        record_id=person.id,
        version=new_version,
        kind="updated",
        changes=[Change(name, None, None) for name in changed],
        source="system",
    )
    await record_event(
        run.session,
        UserUpdated(user_id=person.id, changed_fields=changed, managers=[]),
        aggregate_id=person.id,
        aggregate_version=new_version,
    )
    run.counts["person_fields_cleared"] = len(changed)


_ERASE_PROFILE_HISTORY = text("SELECT audit_erase_profile_history(:person)")


async def _audit(run: _Run) -> None:
    """Step 6: the audit log and record history keep no personal value of theirs (ADR-046)."""
    run.counts["audit_personal_rows_removed"] = await erase_subject(run.session, run.person.id)
    # Their own profile history (record type `user`): the migrator-owned function (0164) acts
    # only once step 5 set `erased_at`, so it can never blank a live person's history.
    blanked = await run.session.scalar(_ERASE_PROFILE_HISTORY, {"person": run.person.id})
    run.counts["profile_history_rows_erased"] = int(blanked or 0)


async def _events(run: _Run) -> None:
    """Step 7: the consumers that react to an erased person, then the completion event."""
    version = await run.session.scalar(select(User.version).where(User.id == run.person.id))
    await record_event(
        run.session,
        UserStatusChanged(user_id=run.person.id, status="disabled", reason="erasure"),
        aggregate_id=run.person.id,
        aggregate_version=version,
    )
    await record_event(
        run.session,
        PersonErasureCompleted(person_id=run.person.id, erasure_id=run.row.id),
        aggregate_id=run.person.id,
        aggregate_version=version,
    )


STEPS: dict[Step, Callable[[_Run], Awaitable[None]]] = {
    Step.RECHECK: _recheck,
    Step.FREEZE: _freeze,
    Step.MAIL: _mail,
    Step.KEYCLOAK: _keycloak,
    Step.PORTS: _ports,
    Step.PERSON_ROW: _person_row,
    Step.AUDIT: _audit,
    Step.EVENTS: _events,
}


# --- running --------------------------------------------------------------------------------------


async def _changed(session: AsyncSession, row: PersonErasure) -> None:
    await record_event(
        session,
        PersonErasureChanged(person_id=row.person_id, state=row.state, step=row.step),  # type: ignore[arg-type]  # a checked state code
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def _audit_outcome(
    session: AsyncSession,
    row: PersonErasure,
    action: str,
    *,
    code: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    await record(
        session,
        action_code=action,
        facts=WORKER,
        outcome=AuditOutcome.DONE if code is None else AuditOutcome.FAILED,
        reason_code=code,
        object_type="user",
        object_id=row.person_id,
        details={"erasure_id": str(row.id), "step": row.step, **(details or {})},
        actor=(AuditActorType.SYSTEM, None),
    )


async def _fail(
    session: AsyncSession,
    row: PersonErasure,
    code: str,
    now: datetime,
    details: Mapping[str, Any] | None = None,
) -> RunOutcome:
    row.state = ErasureState.FAILED.value
    row.last_error_code = code
    row.finished_at = now
    row.version += 1
    await session.flush()
    await _changed(session, row)
    await _audit_outcome(session, row, "person.erasure_failed", code=code, details=details)
    log.warning("person_erasure_failed", erasure_id=str(row.id), step=row.step, code=code)
    return RunOutcome(row.state, row.step, code)


async def _row(session: AsyncSession, erasure_id: uuid.UUID) -> PersonErasure | None:
    return await session.scalar(
        select(PersonErasure).where(PersonErasure.id == erasure_id).with_for_update()
    )


async def _person(session: AsyncSession, person_id: uuid.UUID) -> User:
    person = await session.scalar(
        select(User).where(User.id == person_id).execution_options(populate_existing=True)
    )
    if person is None:  # a foreign key keeps the person; unreachable
        raise StepRefused(rules.APPROVAL_INVALID)
    return person


async def _note_attempt(
    database: Database, tenant_id: uuid.UUID, erasure_id: uuid.UUID, code: str, now: datetime
) -> RunOutcome:
    """A passing failure: count it and keep the code; fail for good after MAX_ATTEMPTS."""
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        row = await _row(session, erasure_id)
        if row is None:  # pragma: no cover - the row was there a moment ago
            return RunOutcome(ErasureState.FAILED.value, 0, code)
        row.attempts += 1
        row.last_error_code = code
        if row.attempts >= rules.MAX_ATTEMPTS:
            return await _fail(session, row, code, now, {"attempts": row.attempts})
        row.state = ErasureState.RUNNING.value
        row.version += 1
        await session.flush()
        await _changed(session, row)
        log.warning("person_erasure_retry", erasure_id=str(row.id), step=row.step, code=code)
        return RunOutcome(row.state, row.step, code)


async def _one_step(  # noqa: C901, PLR0911 - one step's whole life: checks, work, progress, outcome
    database: Database, tenant_id: uuid.UUID, erasure_id: uuid.UUID, effects: JobEffects
) -> RunOutcome | None:
    """Run the next step in its own transaction. None: go on; an outcome: stop here."""
    now = effects.clock.now()
    unavailable: str | None = None
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        row = await _row(session, erasure_id)
        if row is None:
            return RunOutcome(ErasureState.FAILED.value, 0, rules.NOT_FOUND)
        state = ErasureState(row.state)
        if not rules.can("start", state).allowed or row.step >= rules.LAST_STEP:
            return RunOutcome(row.state, row.step, row.last_error_code)
        step = Step(row.step)
        missing = missing_ports() if step <= Step.PORTS else []
        if missing:
            return await _fail(session, row, rules.PORT_MISSING, now, {"missing_ports": missing})
        run = _Run(session, row, await _person(session, row.person_id), effects, now)
        try:
            async with session.begin_nested():
                await STEPS[step](run)
        except StepRefused as refused:
            await session.refresh(row)
            return await _fail(session, row, refused.code, now, refused.details)
        except (StepUnavailable, ErasureStepFailed) as passing:
            unavailable = passing.code
        except Exception as exc:  # noqa: BLE001 - any failure is retried; its code, not its text
            log.warning(
                "person_erasure_step_error",
                erasure_id=str(erasure_id),
                step=int(step),
                error=type(exc).__name__,
            )
            unavailable = rules.STEP_FAILED
        if unavailable is None:
            await session.refresh(row)
            if row.started_at is None:
                row.started_at = now
            row.counts = {
                kind: int(row.counts.get(kind, 0)) + run.counts.get(kind, 0)
                for kind in sorted(set(row.counts) | set(run.counts))
            }
            row.port_module, row.port_cursor = run.next_port
            row.step = int(step) if run.stay else int(step) + 1
            row.attempts = 0
            row.last_error_code = None
            done = row.step >= rules.LAST_STEP
            row.state = (ErasureState.DONE if done else ErasureState.RUNNING).value
            if done:
                row.finished_at = now
            row.version += 1
            await session.flush()
            await _changed(session, row)
            if done:
                await _audit_outcome(session, row, "person.erasure_completed", details=row.counts)
                return RunOutcome(row.state, row.step)
            return None
    return await _note_attempt(database, tenant_id, erasure_id, unavailable, now)


async def run_erasure(
    database: Database, tenant_id: uuid.UUID, erasure_id: uuid.UUID, effects: JobEffects
) -> RunOutcome:
    """Run an approved (or running) erasure from its recorded step on, until done or stopped.

    Every step commits on its own. Safe to call again at any time.
    """
    while True:
        outcome = await _one_step(database, tenant_id, erasure_id, effects)
        if outcome is not None:
            return outcome


# --- the schedule ---------------------------------------------------------------------------------

# Swapped by tests; the identity service account and the session store from settings.
admin_factory: Callable[[Settings], KeycloakAdmin | None] = KeycloakAdmin.from_settings
ender_factory: Callable[[Settings], TenantSessionEnder | None] = worker_session_ender
sessions_factory: Callable[[Settings], KeycloakSessionIds | None] = worker_keycloak_sessions


async def _due(session: AsyncSession, now: datetime) -> list[uuid.UUID]:
    rows = await session.execute(
        select(PersonErasure.id, PersonErasure.attempts, PersonErasure.updated_at).where(
            PersonErasure.state.in_([state.value for state in rules.RUNNABLE_STATES])
        )
    )
    return [
        erasure_id
        for erasure_id, attempts, updated_at in rows
        if updated_at + rules.retry_delay(attempts) <= now
    ]


async def expire_and_audit(session: AsyncSession, now: datetime) -> int:
    """The tenant's requests past their 7 days expire, each audited."""
    expired = await expire_due(session, now)
    for row in expired:
        await _audit_outcome(session, row, "person.erasure_expired")
    return len(expired)


# One schedule run builds at most this many report batches per erasure; the next run goes on.
REPORT_BATCHES_PER_RUN = 200


async def build_reports(database: Database, tenant: uuid.UUID, now: datetime) -> int:
    """The tenant's requested erasures' mentions reports, one port batch per transaction (S1b).

    A failing port stops that erasure's build for this run (retried on the next, from the
    stored port and cursor); its exception's type is logged, never its text.
    """
    async with database.tenant_session(TenantContext(tenant)) as session:
        due = await reports_due(session, now)
    batches = 0
    for erasure_id in due:
        try:
            for _ in range(REPORT_BATCHES_PER_RUN):
                async with database.tenant_session(TenantContext(tenant)) as session:
                    more = await build_report_batch(session, erasure_id)
                batches += 1
                if not more:
                    break
        except Exception as exc:  # noqa: BLE001 - one erasure's port must not stop the others
            log.warning(
                "person_erasure_report_error", erasure_id=str(erasure_id), error=type(exc).__name__
            )
    return batches


async def erasure_schedule(database: Database, settings: Settings) -> None:
    """Every tenant: expire old requests, build mentions reports, then run approved erasures."""
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    now = system_clock.now()
    work: list[tuple[uuid.UUID, uuid.UUID]] = []
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            await expire_and_audit(session, now)
            work += [(tenant, erasure_id) for erasure_id in await _due(session, now)]
        await build_reports(database, tenant, now)
    if not work:
        return
    admin = admin_factory(settings)
    effects = JobEffects(
        identity_admin=admin,
        end_sessions=ender_factory(settings),
        keycloak_sessions=sessions_factory(settings),
    )
    try:
        for tenant, erasure_id in work:
            outcome = await run_erasure(database, tenant, erasure_id, effects)
            log.info(
                "person_erasure_run",
                erasure_id=str(erasure_id),
                state=outcome.state,
                step=outcome.step,
                code=outcome.error_code,
            )
    finally:
        if admin is not None:
            await admin.close()
