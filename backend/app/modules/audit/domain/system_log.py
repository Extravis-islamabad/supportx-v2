"""The system log's catalogue and rules (WP-057 S5b, REQ-AUD-016). Pure.

An entry is a **code** plus small params, never free text (rule 5d): the screen renders each code
through its label, with the params filled in. Every code a module may write is listed here, so
each has an English, Arabic and Urdu label (enforced by test_enum_labels). Params never carry
personal data or secrets: plain counts, codes and short names only, checked by `check_params`.
"""

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

PARAMS_MAX = 12
PARAM_TEXT_MAX = 200
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_OBJECT_TYPE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MODULE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# Names the label renderer takes itself (label(key, language, **params)).
_RESERVED = frozenset({"key", "language"})
_REF = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

ParamValue = str | int | float | bool | None


class SystemLogSeverity(StrEnum):
    """How much an entry matters."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class SystemLogCode(StrEnum):
    """What happened. Grouped by the module that writes it; a new writer adds its codes here."""

    # audit: its own jobs.
    AUDIT_RETENTION_ARCHIVED = "audit.retention.archived"
    AUDIT_RETENTION_FAILED = "audit.retention.failed"
    AUDIT_SYSTEM_LOG_PURGED = "audit.system_log.purged"
    AUDIT_EXPORT_FAILED = "audit.export.failed"
    # files: scanning and purging uploads.
    FILES_SCAN_FAILED = "files.scan.failed"
    FILES_SCAN_INFECTED = "files.scan.infected"
    # integrations: mailboxes, connectors, outbound calls.
    MAILBOX_CHECK_FAILED = "integrations.mailbox.check_failed"
    MAILBOX_SEND_FAILED = "integrations.mailbox.send_failed"
    CONNECTOR_CALL_FAILED = "integrations.connector.call_failed"
    # identity_access: the directory.
    DIRECTORY_SYNC_FINISHED = "identity_access.directory.sync_finished"
    DIRECTORY_SYNC_FAILED = "identity_access.directory.sync_failed"
    # imports and exports of records.
    IMPORT_FINISHED = "imports.finished"
    IMPORT_FAILED = "imports.failed"
    # licensing.
    LICENCE_CHECK_FAILED = "licensing.check_failed"
    # automation: a rule or workflow run that failed (the run record has the detail).
    AUTOMATION_RUN_FAILED = "automation.run.failed"


class SystemLogProblem(ValueError):
    """An entry a writer built wrongly: a bug in the writer, never the user's input."""


@dataclass(frozen=True)
class SystemLogObject:
    """What the entry is about, so the screen can link to it (its type has a route there)."""

    type: str
    id: uuid.UUID

    def __post_init__(self) -> None:
        """Refuse a type that isn't a code."""
        if not _OBJECT_TYPE.match(self.type):
            msg = "an object type is a lowercase code"
            raise SystemLogProblem(msg)


@dataclass(frozen=True)
class SystemLogEntryIn:
    """One entry as a module writes it."""

    module: str
    code: SystemLogCode
    severity: SystemLogSeverity
    params: Mapping[str, ParamValue] = field(default_factory=dict)
    about: SystemLogObject | None = None
    job_id: str | None = None

    def __post_init__(self) -> None:
        """Refuse an entry a writer built wrongly (a bug, caught in its tests)."""
        if not _MODULE.match(self.module):
            msg = "a module is its lowercase code"
            raise SystemLogProblem(msg)
        if not self.code.startswith(_code_prefix(self.module) + "."):
            msg = f"{self.module} writes only its own codes"
            raise SystemLogProblem(msg)
        if self.job_id is not None and not _REF.match(self.job_id):
            msg = "a job ID is a short reference"
            raise SystemLogProblem(msg)
        check_params(self.params)


# Modules whose codes don't start with their own name (records' imports are shared work).
_PREFIXES = {"work_items": "imports", "assets": "imports", "organization": "imports"}


def _code_prefix(module: str) -> str:
    return _PREFIXES.get(module, module)


def check_params(params: Mapping[str, ParamValue]) -> dict[str, ParamValue]:
    """Small, flat and labelled-safe: at most 12 keys, scalar values, short text."""
    if len(params) > PARAMS_MAX:
        msg = "too many params"
        raise SystemLogProblem(msg)
    out: dict[str, ParamValue] = {}
    for key, given in params.items():
        value: object = given  # checked as it comes: writers' params are typed only statically
        if not _KEY.match(key) or key in _RESERVED:
            msg = "a param key is a lowercase code"
            raise SystemLogProblem(msg)
        if isinstance(value, str) and len(value) > PARAM_TEXT_MAX:
            msg = "a param is short text"
            raise SystemLogProblem(msg)
        if value is not None and not isinstance(value, str | int | float | bool):
            msg = "a param is a plain value"
            raise SystemLogProblem(msg)
        out[key] = given
    return out
