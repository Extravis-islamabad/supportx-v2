"""Which export formats this installation can make now (QA6-RPT-01).

PDF needs the worker image's `pdf` dependency group (D-100 D8), which the API process does not
have, so the API cannot tell by itself. The consumers worker, which renders the PDFs, says so
every minute with a short-lived Valkey key (`pdf_heartbeat`); the API offers PDF while the key
is there (`export_formats`). An installation without Valkey (one process) asks its own process.
Nothing here branches on the deployment mode: it asks what is running.
"""

from typing import Any

import valkey.asyncio
import valkey.exceptions

from app.core.config import Settings
from app.core.database import Database
from app.core.valkey import ValkeyNotConfiguredError, client
from app.modules.analytics.service.jobs import _pdf_renderer

PDF_KEY = "supportx:analytics:pdf_export"
PDF_TTL_SECONDS = 180  # three missed minutes and PDF is no longer offered
ALWAYS = ("xlsx", "csv")
_clients: dict[int, Any] = {}


def _valkey(settings: Settings) -> valkey.asyncio.Valkey | None:
    """One client per settings object (process-wide), or None without Valkey."""
    if id(settings) not in _clients:
        try:
            _clients[id(settings)] = client(settings)
        except ValkeyNotConfiguredError:
            _clients[id(settings)] = None
    found: valkey.asyncio.Valkey | None = _clients[id(settings)]
    return found


async def pdf_heartbeat(database: Database, settings: Settings) -> None:
    """Every minute in the worker: PDF can be made here, for the next three minutes."""
    del database  # the schedule's signature; nothing to read
    store = _valkey(settings)
    if store is None or _pdf_renderer() is None:
        return
    try:
        await store.set(PDF_KEY, "1", ex=PDF_TTL_SECONDS)
    except (valkey.exceptions.ValkeyError, OSError):
        return  # Valkey down: the key lapses and PDF stops being offered, as it should


async def export_formats(settings: Settings) -> list[str]:
    """The formats to offer: Excel and CSV always, PDF while a worker can make it."""
    store = _valkey(settings)
    if store is None:
        return [*ALWAYS, *(["pdf"] if _pdf_renderer() is not None else [])]
    try:
        live = bool(await store.exists(PDF_KEY))
    except (valkey.exceptions.ValkeyError, OSError):
        live = False
    return [*ALWAYS, *(["pdf"] if live else [])]
