"""Knowledge article files through the shared files service (WP-033 session 2, lane B's review).

The files port answers per record type: `GET /files/records/kb_article/{id}` asks knowledge
(the article's reader rule, REQ-KB-048), never work items, and a file change is announced on the
article's own channel (rule c). Same world and fixtures as test_files_api.py.
"""

import json
import uuid

import pytest

from app.modules.system.service.files import REALTIME
from app.shared.events import EventEnvelope
from app.shared.files.service.core import FileServices
from tests.db.test_files_api import files, scan_waiting, storage, upload
from tests.db.test_incidents_api import World, problem, world
from tests.db.test_knowledge_api import _topic
from tests.db.test_knowledge_review_api import _published

__all__ = ["files", "storage", "world"]  # fixtures, re-used

pytestmark = [pytest.mark.db]


async def test_article_files_follow_the_article_and_its_channel(
    world: World, files: FileServices
) -> None:
    del files
    a = world.a
    network = await _topic(world, a, "Network", tech_all=False, tech_groups=[str(a.ga)])
    article = await _published(world, a, network)
    # tech_a wrote it (an editor); tech_c reads it (GA); tech_b (GB) and requesters do not.
    sent = await upload(world, a, a.tech_a, ("kb_article", article["id"]), b"diagram", "net.txt")
    assert sent.status_code == 201, sent.text
    await scan_waiting(world)

    url = f"/files/records/kb_article/{article['id']}"
    for reader in (a.tech_a, a.tech_c):
        listed = await world.call("GET", url, a, reader)
        assert listed.status_code == 200, listed.text
        assert [f["id"] for f in listed.json()] == [sent.json()["id"]]
    for outsider in (a.tech_b, a.requester):
        hidden = await world.call("GET", url, a, outsider)
        assert problem(hidden) == (404, "file_owner_not_found")
    unknown = await world.call("GET", f"/files/records/no_such_type/{article['id']}", a, a.admin)
    assert problem(unknown) == (404, "file_owner_not_found")
    # A reader may not add files to an article they cannot edit.
    refused = await upload(world, a, a.tech_c, ("kb_article", article["id"]), b"x", "x.txt")
    assert refused.status_code == 403, refused.text

    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND envelope->>'aggregate_type' = 'file' ORDER BY id",
        a.tenant,
    )
    (route,) = REALTIME
    for row in rows:
        envelope = EventEnvelope.model_validate(json.loads(row["envelope"]))
        assert envelope.payload["record_type"] == "kb_article"
        effects = await route.route(envelope, None)  # type: ignore[arg-type]  # unused session
        assert [p.channel.name for p in effects.publications] == [
            f"t:{a.tenant}:kb:{uuid.UUID(article['id'])}"
        ]
