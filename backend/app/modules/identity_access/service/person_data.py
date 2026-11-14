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
"""

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

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
