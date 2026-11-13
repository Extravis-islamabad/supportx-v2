"""The DB-IP Lite city database, read with `maxminddb` (WP-057 S2b; D-170).

One reader per process, opened on first use from `geoip_db` (a mounted file, never in the image)
and memory-mapped by the C extension, so a lookup is a few microseconds and needs no I/O of ours.
Every failure (no setting, a missing or corrupt file, an address the file does not know) answers
None: the place is help for the person reading a sign-in, never a reason to fail one.

The database's build date is shown to admins (D-170: they can see how old it is); DB-IP Lite is
CC BY 4.0, credited on the About page.
"""

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import maxminddb

from app.core.logging import get_logger
from app.modules.identity_access.domain.place import GeoHit, IpAddress

log = get_logger(__name__)


class GeoIp:
    """Lookups in one database file; None everywhere when it cannot be read."""

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._reader: Any = None  # Any: maxminddb's Reader (C extension, untyped)
        self._failed = path is None

    def _open(self) -> Any:  # noqa: ANN401 - maxminddb's Reader
        if self._reader is not None or self._failed:
            return self._reader
        with self._lock:
            if self._reader is None and not self._failed:
                try:
                    self._reader = maxminddb.open_database(str(self._path), maxminddb.MODE_MMAP_EXT)
                except (OSError, ValueError, maxminddb.InvalidDatabaseError):
                    # Logged once: an unreadable file means no place, not a broken sign-in.
                    log.warning("geoip_unavailable", path=str(self._path))
                    self._failed = True
        return self._reader

    def lookup(self, address: IpAddress) -> GeoHit | None:
        """The city and country the database gives the address, or None."""
        reader = self._open()
        if reader is None:
            return None
        try:
            record = reader.get(str(address))
        except (ValueError, maxminddb.InvalidDatabaseError):
            return None
        return _hit(record)

    def built_at(self) -> datetime | None:
        """When the database was built (shown to admins), or None without one."""
        reader = self._open()
        if reader is None:
            return None
        epoch = getattr(reader.metadata(), "build_epoch", None)
        return datetime.fromtimestamp(int(epoch), UTC) if epoch else None


def _hit(record: object) -> GeoHit | None:
    """DB-IP's record (the GeoIP2 City layout): the English city name and the country code."""
    if not isinstance(record, dict):
        return None
    city = record.get("city")
    names = city.get("names") if isinstance(city, dict) else None
    country = record.get("country")
    code = country.get("iso_code") if isinstance(country, dict) else None
    name = names.get("en") if isinstance(names, dict) else None
    if name is None and code is None:
        return None
    return GeoHit(
        city=name if isinstance(name, str) else None,
        country=code if isinstance(code, str) else None,
    )
