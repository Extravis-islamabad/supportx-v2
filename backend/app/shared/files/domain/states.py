"""A file's life: uploaded, scanned, usable or blocked, deleted (WP-022, REQ-INC-079)."""

from enum import StrEnum


class FileState(StrEnum):
    """Where a file is. Only `clean` (and `not_scanned` when scanning is not required) opens."""

    SCANNING = "scanning"  # stored, waiting for (or in) the malware scan
    CLEAN = "clean"
    INFECTED = "infected"  # blocked for good; its object is deleted at once
    SCAN_FAILED = "scan_failed"  # the scanner could not check it (retries exhausted)
    NOT_SCANNED = "not_scanned"  # no scanner, and the installation does not require one
    DELETED = "deleted"  # removed; the object goes after the grace period


FINAL = frozenset({FileState.INFECTED, FileState.DELETED})
SCAN_RESULTS = frozenset(
    {FileState.CLEAN, FileState.INFECTED, FileState.SCAN_FAILED, FileState.NOT_SCANNED}
)
SCAN_ATTEMPTS_MAX = 3


def openable(state: FileState, *, scan_required: bool) -> bool:
    """Whether the file may be previewed or downloaded."""
    if state == FileState.CLEAN:
        return True
    return state == FileState.NOT_SCANNED and not scan_required


def may_become(current: FileState, new: FileState) -> bool:
    """Allowed moves. A blocked or deleted file never comes back; a scan result follows a scan."""
    if current in FINAL:
        return False
    if new == FileState.DELETED:
        return True
    if new in SCAN_RESULTS:
        return current in {FileState.SCANNING, FileState.SCAN_FAILED, FileState.NOT_SCANNED}
    return new == FileState.SCANNING and current in {FileState.SCAN_FAILED, FileState.NOT_SCANNED}
