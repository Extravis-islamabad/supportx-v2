"""The person-data port registry (ADR-052 §4): every module that holds person data registers here.

A module implements `PersonData` and calls `register_person_data(impl)` at import. The erasure
job (service/erasure_job.py) runs every registered port in registry order inside the job's
tenant session, after the person is frozen and before their own row is anonymised. It refuses to
start while a module named in `REQUIRED_PORTS` has not registered: a missing port is a release
defect, never a silent skip.

Order bands (lane C's review): 100-199 references (lists, recipients, memberships), 500-599
owned objects and personal rows, 900-999 derived data (AI summaries and embeddings), so derived
data goes after the text it came from is blanked. A port picks a number inside its band; ties
run in key order. A port's `module` is its registry key: the module's name, or
`<module>.<part>` when a module has work in more than one band (lane A: work_items' references
in band 100, its owned rows in band 500). REQUIRED_PORTS lists keys.

Each port declares the `kinds` its counts use; the job refuses an undeclared one, and every kind
has a label `erasure_count.<kind>` in en/ar/ur (the erasure screens show the counts; a test
checks the labels). A port raises `ErasureStepFailed(code)` for a failure it can name: the job
retries it and records the code, never an exception's text.

S1 defines erasure only. `export_person` (with its streaming `ExportWriter`, ADR-052 §4) joins
the protocol with the export job in S3; ports then add it.

**Mentions (S1b, D-171 a).** A module whose text other people write may name the person
implements `PersonMentions` and calls `register_mentions(impl)`, with the same registry key as its
erasure port (one object may implement both). `find_mentions` returns where the person is named
(record, field, kind, count: never text) in bounded batches; `redact_mention` replaces the matched
occurrences in that one field with the D2a marker; `passage` returns the field's current text
to someone whose own rights let them read the record. The report is complete only when every
key in `REQUIRED_MENTION_PORTS` has run, and approval waits for a complete, reviewed report.
"""

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access.domain.mentions import MentionMatchKind, MentionTerms

if TYPE_CHECKING:
    from app.modules.identity_access.domain.policy import Subject

# Batches (lane A's review): one call does at most this many rows and returns a cursor; the job
# commits, stores the cursor and calls again in a fresh transaction until it is None.
ERASE_BATCH = 500

REFERENCES = range(100, 200)
OWNED = range(500, 600)
DERIVED = range(900, 1000)
BANDS = (REFERENCES, OWNED, DERIVED)

# The ports the job will not run without. S1: lane B's own ports (built with the job). S2 adds
# lane A's (work_items, notifications, integrations, automation, sla) and lane C's (knowledge,
# analytics, announcements, ai) as each lands; keep this the one place that lists them.
REQUIRED_PORTS: frozenset[str] = frozenset(
    {
        "action_links",
        "audit",
        "files",
        "identity_access",
        "list_settings",
        "organization",
        # Lane A's (0166): references before owned rows.
        "work_items.references",
        "work_items.owned",
        "notifications",
        "automation",
        "integrations",
        "sla",
        # Lane C's S2 ports (knowledge, analytics, announcements, ai).
        "knowledge",
        "analytics.recipients",
        "analytics",
        "announcements",
        "ai",
    }
)


_KEY = re.compile(r"^[a-z][a-z0-9_]{0,40}(\.[a-z][a-z0-9_]{0,15})?$")
_KIND = re.compile(r"^[a-z][a-z0-9_]{0,60}$")


def count_label(kind: str) -> str:
    """The label key a count kind is shown with."""
    return f"erasure_count.{kind}"


class ErasureStepFailed(Exception):
    """A port's failure it can name (a coded `errors.<code>`): retried, the code recorded."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ErasureBatch:
    """One bounded batch of a port's erasure: counts by kind (never data), and where to go on.

    `cursor` None: the module is done for this person; otherwise the job calls again with it.
    A cursor is the port's own opaque text (at most 2,000 characters), never personal data.
    """

    counts: Mapping[str, int]
    cursor: str | None = None


@runtime_checkable
class PersonData(Protocol):
    """One module's slice of a person's erasure (ADR-052 §4).

    `erase_person` runs in the job's tenant session (RLS), does at most ERASE_BATCH rows per call
    and returns the cursor to go on with (None when done), is idempotent (a second call changes
    nothing and returns zero counts), deletes the person's private data, moves shared objects
    they own to `successor_id`, deletes files they uploaded unless kept, and returns counts by
    kind only: never data, in counts, logs or errors.
    """

    module: ClassVar[str]  # the registry key: "<module>" or "<module>.<part>"
    order: ClassVar[int]
    kinds: ClassVar[frozenset[str]]  # the count kinds it may return (each labelled)

    async def erase_person(  # noqa: D102, PLR0913 - see the class docstring; the contract
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch: ...


class PortRegistrationError(RuntimeError):
    """A port with a bad key or kinds, outside the bands, or a second one for a key."""


_PORTS: dict[str, PersonData] = {}


def register_person_data(port: PersonData) -> None:
    """Register a module's port (at module import). Registering the same object again is fine."""
    name = port.module
    if not name or not _KEY.fullmatch(name):
        msg = f"person-data port needs a key like 'module' or 'module.part', got {name!r}"
        raise PortRegistrationError(msg)
    if not port.kinds or not all(_KIND.fullmatch(kind) for kind in port.kinds):
        msg = f"person-data port {name!r} must declare its count kinds as codes"
        raise PortRegistrationError(msg)
    if not any(port.order in band for band in BANDS):
        msg = f"person-data port {name!r} has order {port.order} outside the bands"
        raise PortRegistrationError(msg)
    current = _PORTS.get(name)
    if current is not None and current is not port:
        msg = f"person-data port {name!r} is registered twice"
        raise PortRegistrationError(msg)
    _PORTS[name] = port


def unregister_person_data(module: str) -> None:
    """Take a port out (tests only: a missing required port must stop the job)."""
    _PORTS.pop(module, None)


def registered_ports() -> list[PersonData]:
    """Every registered port, in the order the job runs them."""
    return sorted(_PORTS.values(), key=lambda port: (port.order, port.module))


def missing_ports(required: frozenset[str] = REQUIRED_PORTS) -> list[str]:
    """Required modules with no registered port (sorted)."""
    return sorted(required - set(_PORTS))


# --- mentions (S1b, D-171 a) ----------------------------------------------------------------------

MENTION_BATCH = 500  # rows a find_mentions call looks at, at most

# The mention ports the report is not complete without (the one place that lists them). S1b
# ships identity_access's, files' and assets'; the others land with S2 (lane A's work items and
# integrations, lane C's knowledge and announcements). Until they do, every report stays
# incomplete, so approval stays refused in practice (erasure_report_unavailable): no erasure can
# run before S2. Never shrink this to make a report complete.
REQUIRED_MENTION_PORTS: frozenset[str] = frozenset(
    {
        "identity_access",
        "assets",
        "files",
        "work_items",
        "integrations",
        "knowledge",
        "announcements",
    }
)


@dataclass(frozen=True)
class Mention:
    """One place the person is named: a field of a record, by kind, how often. Never the text."""

    record_type: str
    record_id: uuid.UUID
    field: str
    match_kind: MentionMatchKind
    occurrences: int
    # The report's row (set when the registry calls a port): a port whose definer function is
    # bound to the redacted mention passes it on (lane C's knowledge port, 0168).
    mention_id: uuid.UUID | None = None


@dataclass(frozen=True)
class MentionBatch:
    """One bounded batch of a port's search, and where to go on (None: done)."""

    mentions: tuple[Mention, ...]
    cursor: str | None = None


@runtime_checkable
class PersonMentions(Protocol):
    """One module's part of the mentions report and redaction (ADR-052 S1b).

    All three run in a tenant session (RLS). `find_mentions` looks at no more than
    MENTION_BATCH rows per call, skips the person's own records where those are the erasure's
    to clear, and returns mentions only (no snippets, no text). `redact_mention` replaces only
    the occurrences of `mention.match_kind` in that one field of that one record with `marker`
    (the reserved code, labelled by the UI), bumps the record's version, writes history naming
    the field only (old and new None, reason `erasure_redaction`) and the record's ordinary
    change event; it returns False when nothing matched any more (idempotent). `passage` returns
    the field's current text when `subject`'s own rights let them read the record **and that
    field** (its own field rules, and ADR-047 field access: a field a role hides or masks from
    them is None; the registry also checks field access by the mention's record type and field
    name, so a port names fields as its field catalogue does), else None.

    Scale (lane A's #506 review): `find_mentions` may narrow its scan with an index (full-text,
    trigram) as long as it never misses an exact match; it confirms each candidate with
    `count_matches`. Rich text (sanitised HTML) uses `count_matches_html` / `redact_html`: text
    between tags only, never a tag or an attribute.
    """

    module: ClassVar[str]  # the registry key, as the erasure port's

    async def find_mentions(  # noqa: D102 - see the class docstring; the contract
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        terms: MentionTerms,
        cursor: str | None,
    ) -> MentionBatch: ...

    async def redact_mention(  # noqa: D102 - see the class docstring; the contract
        self,
        session: AsyncSession,
        mention: Mention,
        *,
        terms: MentionTerms,
        marker: str,
        now: datetime,
    ) -> bool: ...

    async def passage(  # noqa: D102 - see the class docstring; the contract
        self, session: AsyncSession, subject: "Subject", mention: Mention
    ) -> str | None: ...


_MENTIONS: dict[str, PersonMentions] = {}


def register_mentions(port: PersonMentions) -> None:
    """Register a module's mentions port (at module import). The same object again is fine."""
    name = port.module
    if not name or not _KEY.fullmatch(name):
        msg = f"mentions port needs a key like 'module' or 'module.part', got {name!r}"
        raise PortRegistrationError(msg)
    current = _MENTIONS.get(name)
    if current is not None and current is not port:
        msg = f"mentions port {name!r} is registered twice"
        raise PortRegistrationError(msg)
    _MENTIONS[name] = port


def unregister_mentions(module: str) -> None:
    """Take a mentions port out (tests only)."""
    _MENTIONS.pop(module, None)


def mention_ports() -> list[PersonMentions]:
    """Every registered mentions port, in the order the report runs them (by key)."""
    return [_MENTIONS[key] for key in sorted(_MENTIONS)]


def mention_port(module: str) -> PersonMentions | None:
    """The mentions port registered under `module`, if any."""
    return _MENTIONS.get(module)


def missing_mention_ports(
    done: frozenset[str] | set[str], required: frozenset[str] = REQUIRED_MENTION_PORTS
) -> list[str]:
    """Required mention ports that have not run (sorted)."""
    return sorted(required - set(done))
