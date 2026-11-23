"""Which codes a module may write to the system log (WP-046b S5 follow-up; lane C's conditions).

A module always writes its own codes; `_PREFIXES` only adds shared ones (records' imports), and
never hands one module's own prefix to another.
"""

import pytest

from app.modules.audit.domain.system_log import (
    SystemLogCode,
    SystemLogEntryIn,
    SystemLogProblem,
    SystemLogSeverity,
)

OWN = SystemLogCode.CANCELLATION_WITHOUT_DECIDER  # work_items.*
SHARED = SystemLogCode.IMPORT_FINISHED  # imports.*


def _entry(module: str, code: SystemLogCode) -> SystemLogEntryIn:
    return SystemLogEntryIn(module=module, code=code, severity=SystemLogSeverity.WARNING)


def test_work_items_writes_its_own_codes_and_the_shared_imports() -> None:
    assert _entry("work_items", OWN).code is OWN
    assert _entry("work_items", SHARED).code is SHARED


@pytest.mark.parametrize("module", ["assets", "organization", "files", "integrations"])
def test_no_other_module_writes_work_items_codes(module: str) -> None:
    with pytest.raises(SystemLogProblem):
        _entry(module, OWN)


@pytest.mark.parametrize("module", ["work_items", "assets", "organization", "integrations"])
def test_only_files_writes_files_codes(module: str) -> None:
    with pytest.raises(SystemLogProblem):
        _entry(module, SystemLogCode.FILES_SCAN_FAILED)
    assert _entry("files", SystemLogCode.FILES_SCAN_FAILED).module == "files"


def test_the_shared_imports_stay_with_the_record_modules() -> None:
    assert _entry("assets", SHARED).code is SHARED
    with pytest.raises(SystemLogProblem):
        _entry("integrations", SHARED)
