"""Knowledge on incidents over HTTP (WP-033 session 4, D-121; REQ-KB-016, 063, 064).

Both rules always apply: the article's reader rule and the incident's (through the shared
records port, which work_items answers with GET /incidents/{id}'s rule). Copied images follow
lane B's conditions. The incident world of test_incidents_api.py; real object storage and the
fake scanner of test_files_api.py.
"""

import dataclasses
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.shared.files.ports import register_quota
from app.shared.files.service.copies import CopyIntegrityError
from app.shared.files.service.core import FileServices
from app.shared.records.ports import BATCH_MAX, record_facts
from tests.db.test_conversation_api import say
from tests.db.test_files_api import (
    _photo_with_gps,
    files,
    open_file,
    scan_waiting,
    storage,
    upload,
    use,
)
from tests.db.test_incidents_api import Org, World, problem, role, world
from tests.db.test_knowledge_api import _article, _new, _topic
from tests.db.test_knowledge_review_api import _approve, _submit

__all__ = ["files", "storage", "world"]  # fixtures, re-used
pytestmark = [pytest.mark.db]

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


async def _published_with_image(
    world: World,
    org: Org,
    topic: dict[str, Any],
    extra_html: str = "",
    picture: tuple[bytes, str] = (PNG, "shot.png"),
) -> tuple[dict[str, Any], str]:
    """An article tech_a wrote with one inline image, approved by the admin."""
    article = await _article(world, org, org.tech_a, topic, title="VPN token")
    data, name = picture
    sent = await upload(world, org, org.tech_a, ("kb_article", article["id"]), data, name)
    assert sent.status_code == 201, sent.text
    image = sent.json()["id"]
    await scan_waiting(world)
    await world.sql(
        "UPDATE kb_article_versions SET body_html = $2 WHERE article_id = $1",
        uuid.UUID(article["id"]),
        f'<p>Open the portal.</p><img data-file-id="{image}" alt="portal">{extra_html}',
    )
    await _submit(world, org, org.tech_a, article)
    approved = await _approve(world, org, org.admin, article)
    assert approved.status_code == 200, approved.text
    return article, image


def _apply(item: dict[str, Any], **extra: str) -> dict[str, Any]:
    return {
        "record_type": "incident",
        "record_id": item["id"],
        "audience": "public",
        "mode": "content",
        **extra,
    }


# --- the records port (lane A's conditions) -------------------------------------------------------


async def test_the_records_port_uses_the_incident_read_rule(world: World) -> None:
    a, b = world.a, world.b
    in_ga = await world.create(a, a.admin, group_id=str(a.ga))
    assigned = await world.create(a, a.admin, group_id=str(a.ga))
    await world.sql(
        "UPDATE work_items SET technician_id = $2 WHERE id = $1",
        uuid.UUID(assigned["id"]),
        a.tech_b,
    )
    trashed = await world.create(a, a.admin, group_id=str(a.ga))
    await world.sql(
        "UPDATE work_items SET deleted_at = now() WHERE id = $1", uuid.UUID(trashed["id"])
    )
    ids = [uuid.UUID(i["id"]) for i in (in_ga, assigned, trashed)]
    facts = record_facts("incident")
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        admin = await subject_for(session, a.tenant, a.admin)
        assert await facts.visible(session, admin, ids) == set(ids[:2])  # trash never
        # tech_b (group GB): not GA's queue, but their own assigned one (scope "own", D-052).
        tech_b = await subject_for(session, a.tenant, a.tech_b)
        assert await facts.visible(session, tech_b, ids) == {uuid.UUID(assigned["id"])}
        # Requesters hold no incidents.view: GET /incidents/{id} is 404 for them, so is this.
        requester = await subject_for(session, a.tenant, a.requester)
        assert await facts.visible(session, requester, ids) == set()
        people = await facts.requester_of(session, admin, uuid.UUID(in_ga["id"]))
        assert people is not None
        assert people.ids == {a.requester}
        assert await facts.requester_of(session, tech_b, uuid.UUID(in_ga["id"])) is None
        lines = await facts.summaries(session, tech_b, ids)
        assert [s.display_id for s in lines.values()] == [assigned["display_id"]]
        with pytest.raises(ValueError, match="at most"):
            await facts.visible(session, admin, [uuid.uuid4() for _ in range(BATCH_MAX + 1)])
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        other = await subject_for(session, b.tenant, b.admin)
        assert await facts.visible(session, other, ids) == set()  # tenant B: nothing


async def test_resolution_of_needs_sight_and_a_resolution(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    facts = record_facts("incident")
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        admin = await subject_for(session, a.tenant, a.admin)
        assert await facts.resolution_of(session, admin, uuid.UUID(item["id"])) is None
    await world.sql(
        "UPDATE work_items SET resolution = '<p>أعد تشغيل الموجه</p>' WHERE id = $1",
        uuid.UUID(item["id"]),
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        admin = await subject_for(session, a.tenant, a.admin)
        found = await facts.resolution_of(session, admin, uuid.UUID(item["id"]))
        assert found is not None
        assert (found.subject, found.language) == ("Mail is down", "ar")
        tech_b = await subject_for(session, a.tenant, a.tech_b)
        assert await facts.resolution_of(session, tech_b, uuid.UUID(item["id"])) is None


# --- links (REQ-KB-064) ---------------------------------------------------------------------------


async def test_links_show_both_ends_only_to_who_may_read_both(world: World) -> None:
    a = world.a
    topic = await _topic(world, a, "Network", tech_all=False, tech_groups=[str(a.ga)])
    article = await _article(world, a, a.tech_a, topic)
    item = await world.create(a, a.admin, group_id=str(a.ga))
    hidden = await world.create(a, a.admin, group_id=str(a.gb))
    url = f"/knowledge/articles/{article['id']}/links"
    made = await world.call(
        "POST",
        url,
        a,
        a.tech_a,
        json={"record_type": "incident", "record_id": item["id"]},
        headers=_new(),
    )
    assert made.status_code == 201, made.text
    assert made.json()["display_id"] == item["display_id"]
    again = await world.call(
        "POST",
        url,
        a,
        a.tech_a,
        json={"record_type": "incident", "record_id": item["id"]},
        headers=_new(),
    )
    assert again.json()["link_id"] == made.json()["link_id"]  # once
    # tech_a cannot open the GB incident: refused as "not found", never linked.
    refused = await world.call(
        "POST",
        url,
        a,
        a.tech_a,
        json={"record_type": "incident", "record_id": hidden["id"]},
        headers=_new(),
    )
    assert problem(refused) == (404, "kb_record_not_found")
    # The admin links the GB one too; tech_a sees one record and "1 restricted".
    await world.call(
        "POST",
        url,
        a,
        a.admin,
        json={"record_type": "incident", "record_id": hidden["id"]},
        headers=_new(),
    )
    listed = (await world.call("GET", url, a, a.tech_a)).json()
    assert [i["record_id"] for i in listed["items"]] == [item["id"]]
    assert listed["restricted"] == 1
    # The incident side: tech_b (GB) cannot read the article, so it is only counted.
    side = f"/knowledge/records/incident/{hidden['id']}/articles"
    seen = (await world.call("GET", side, a, a.tech_b)).json()
    assert (seen["items"], seen["restricted"]) == ([], 1)
    assert problem(await world.call("GET", side, a, a.tech_a)) == (404, "kb_record_not_found")
    # Requesters never see links.
    assert problem(await world.call("GET", url, a, a.requester))[0] in (403, 404)
    # Unlink: an editor of the article; history and the outbox record it.
    gone = await world.call("DELETE", f"{url}/{made.json()['link_id']}", a, a.tech_a)
    assert gone.status_code == 204, gone.text
    events = await world.sql(
        "SELECT event_type FROM outbox_events WHERE tenant_id = $1"
        " AND event_type LIKE 'knowledge.link.%' ORDER BY id",
        a.tenant,
    )
    assert [e["event_type"] for e in events] == [
        "knowledge.link.saved",
        "knowledge.link.saved",
        "knowledge.link.removed",
    ]


async def test_kb_record_links_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    topic = await _topic(world, a)
    article = await _article(world, a, a.admin, topic)
    item = await world.create(a, a.admin)
    await world.call(
        "POST",
        f"/knowledge/articles/{article['id']}/links",
        a,
        a.admin,
        json={"record_type": "incident", "record_id": item["id"]},
        headers=_new(),
    )
    import asyncpg  # noqa: PLC0415 - the app role's own connection

    conn = await asyncpg.connect(world.db.app_direct_url)
    try:
        async with conn.transaction():
            await conn.execute(f"SET LOCAL app.tenant_id = '{b.tenant}'")
            assert await conn.fetch("SELECT id FROM kb_record_links") == []
            with pytest.raises(asyncpg.PostgresError):
                await conn.execute(
                    "INSERT INTO kb_record_links (id, tenant_id, article_id, record_type,"
                    " record_id, source) VALUES ($1, $2, $3, 'incident', $4, 'link')",
                    uuid.uuid4(),
                    a.tenant,
                    uuid.UUID(article["id"]),
                    uuid.UUID(item["id"]),
                )
    finally:
        await conn.close()


# --- apply to a reply (REQ-KB-063, D-108 (3)) ---------------------------------------------


async def test_apply_check_is_the_servers_answer_for_the_requester(
    world: World, files: FileServices
) -> None:
    del files
    a = world.a
    staff_only = await _topic(world, a, "Internal")
    for_all = await _topic(world, a, "Help", requesters="all")
    internal, _ = await _published_with_image(world, a, staff_only)
    public, _ = await _published_with_image(world, a, for_all)
    item = await world.create(a, a.admin)  # requester: org.requester
    for article, expected in ((internal, False), (public, True)):
        found = await world.call(
            "GET",
            f"/knowledge/articles/{article['id']}/apply-check",
            a,
            a.tech_a,
            params={"record_type": "incident", "record_id": item["id"], "audience": "public"},
        )
        assert found.status_code == 200, found.text
        assert found.json()["visible_to_requester"] is expected
    private = await world.call(
        "GET",
        f"/knowledge/articles/{internal['id']}/apply-check",
        a,
        a.tech_a,
        params={"record_type": "incident", "record_id": item["id"], "audience": "private"},
    )
    assert private.json()["visible_to_requester"] is None


async def test_applied_images_are_copies_the_requester_reads_only_through_the_reply(
    world: World, files: FileServices
) -> None:
    del files
    a = world.a
    topic = await _topic(world, a, "Help", requesters="all")
    article, image = await _published_with_image(world, a, topic)
    item = await world.create(a, a.admin)
    applied = await world.call(
        "POST",
        f"/knowledge/articles/{article['id']}/apply",
        a,
        a.tech_a,
        json=_apply(item),
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["images_not_copied"] == []
    assert image not in body["html"]
    copy = body["html"].split('data-file-id="')[1].split('"')[0]
    row = (
        await world.sql(
            "SELECT state, copied_from, source FROM files WHERE id = $1", uuid.UUID(copy)
        )
    )[0]
    assert (row["state"], row["copied_from"], row["source"]) == (
        "clean",
        uuid.UUID(image),
        "knowledge",
    )
    # A draft: only its author reads it until a reply claims it.
    assert (await open_file(world, a, a.tech_a, copy, "inline")).status_code == 200
    for other in (a.tech_c, a.requester):
        assert (await open_file(world, a, other, copy, "inline")).status_code == 404
    # The reply saved and the draft attached: the requester reads the copy through the reply
    # (their own incidents, as the portal will give them: incidents.view at scope own).
    own = await role(world, a, "Own incidents", [("incidents.view", "own")])
    granted = await world.call("PUT", f"/users/{a.requester}/roles/{own}", a, a.admin)
    assert granted.status_code == 204, granted.text
    reply = await say(
        world, a, a.tech_a, item, kind="reply", visibility="public", body=body["html"]
    )
    assert reply.status_code == 201, reply.text
    attached = await world.call(
        "POST",
        "/files/attach",
        a,
        a.tech_a,
        json={
            "owner_type": "conversation_entry",
            "owner_id": reply.json()["entry"]["id"],
            "file_ids": [copy],
        },
    )
    assert attached.status_code == 200, attached.text
    await scan_waiting(world)
    assert (await open_file(world, a, a.requester, copy, "inline")).status_code == 200
    # The link was recorded as an insert.
    links = (
        await world.call("GET", f"/knowledge/articles/{article['id']}/links", a, a.tech_a)
    ).json()
    assert [(i["record_id"], i["source"]) for i in links["items"]] == [(item["id"], "insert")]


async def test_nothing_is_copied_for_an_article_the_actor_cannot_read(
    world: World, files: FileServices
) -> None:
    del files
    a = world.a
    ga_only = await _topic(world, a, "Network", tech_all=False, tech_groups=[str(a.ga)])
    article, image = await _published_with_image(world, a, ga_only)
    item = await world.create(a, a.admin, group_id=str(a.gb))
    before = (await world.sql("SELECT count(*) AS n FROM files WHERE tenant_id = $1", a.tenant))[0][
        "n"
    ]
    refused = await world.call(
        "POST",
        f"/knowledge/articles/{article['id']}/apply",
        a,
        a.tech_b,
        json=_apply(item),
    )
    assert problem(refused) == (404, "kb_article_not_found")
    after = (await world.sql("SELECT count(*) AS n FROM files WHERE tenant_id = $1", a.tenant))[0][
        "n"
    ]
    assert after == before
    # Nor can tech_b read the source image itself.
    assert (await open_file(world, a, a.tech_b, image, "inline")).status_code == 404


# --- copy_to_drafts (lane B's conditions) -------------------------------------------------------


async def test_copies_refuse_foreign_files_and_name_unsafe_ones(
    world: World, files: FileServices
) -> None:
    a = world.a
    topic = await _topic(world, a, "Help")
    item = await world.create(a, a.admin)
    # A file of another owner (the incident), named in an article's body: 404, nothing copied.
    other = await upload(world, a, a.tech_a, ("work_item", item["id"]), PNG, "other.png")
    assert other.status_code == 201, other.text
    foreign_html = f'<img data-file-id="{other.json()["id"]}" alt="x">'
    sneaky, _ = await _published_with_image(world, a, topic, foreign_html)
    foreign = await world.call(
        "POST", f"/knowledge/articles/{sneaky['id']}/apply", a, a.tech_a, json=_apply(item)
    )
    assert problem(foreign) == (404, "file_not_found")
    article, image = await _published_with_image(world, a, topic)
    # An infected source is named, not copied, and left out of the HTML.
    await world.sql("UPDATE files SET state = 'infected' WHERE id = $1", uuid.UUID(image))
    named = await world.call(
        "POST",
        f"/knowledge/articles/{article['id']}/apply",
        a,
        a.tech_a,
        json=_apply(item),
    )
    assert named.status_code == 200, named.text
    assert named.json()["images_not_copied"] == [{"file_id": image, "reason": "infected"}]
    assert "data-file-id" not in named.json()["html"]
    # not_scanned (scanning not required) with a scanner present now: the copy is scanned
    # like a new upload, never handed on as "not scanned".
    use(world, dataclasses.replace(files, scan_required=False))
    await world.sql("UPDATE files SET state = 'not_scanned' WHERE id = $1", uuid.UUID(image))
    fresh = await world.call(
        "POST",
        f"/knowledge/articles/{article['id']}/apply",
        a,
        a.tech_a,
        json=_apply(item),
    )
    copy = fresh.json()["html"].split('data-file-id="')[1].split('"')[0]
    state = await world.sql("SELECT state FROM files WHERE id = $1", uuid.UUID(copy))
    assert state[0]["state"] == "scanning"


class _Recorder:
    """The world's storage, noting what is written and deleted."""

    def __init__(self, inner: Any) -> None:  # noqa: ANN401 - any ObjectStorage
        self.inner = inner
        self.written: list[str] = []
        self.deleted: list[str] = []

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 - delegated
        return getattr(self.inner, name)

    async def put_stream(self, key: str, parts: AsyncIterator[bytes], content_type: str) -> int:
        self.written.append(key)
        return int(await self.inner.put_stream(key, parts, content_type))

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        await self.inner.delete(key)


async def test_a_tampered_source_or_a_full_quota_copies_nothing(
    world: World, files: FileServices
) -> None:
    a = world.a
    topic = await _topic(world, a, "Help")
    article, image = await _published_with_image(world, a, topic)
    item = await world.create(a, a.admin)
    count = "SELECT count(*) AS n FROM files WHERE tenant_id = $1"
    before = (await world.sql(count, a.tenant))[0]["n"]
    recorder = _Recorder(files.storage)
    use(world, dataclasses.replace(files, storage=recorder))
    # The bytes no longer match the source's sha256: no copy, and its object is removed.
    sha = (await world.sql("SELECT sha256 FROM files WHERE id = $1", uuid.UUID(image)))[0]["sha256"]
    await world.sql("UPDATE files SET sha256 = $2 WHERE id = $1", uuid.UUID(image), b"\x00" * 32)
    try:
        failed = await world.call(
            "POST",
            f"/knowledge/articles/{article['id']}/apply",
            a,
            a.tech_a,
            json=_apply(item),
        )
        assert failed.status_code == 500
    except CopyIntegrityError:  # the test client may raise the app's error instead
        pass
    assert recorder.written, "the copy was attempted"
    assert sorted(recorder.deleted) == sorted(recorder.written)
    assert (await world.sql(count, a.tenant))[0]["n"] == before
    # Over the storage quota: refused before anything is written.
    await world.sql("UPDATE files SET sha256 = $2 WHERE id = $1", uuid.UUID(image), sha)
    recorder.written.clear()
    used = (await world.call("GET", "/files/settings/usage", a, a.admin)).json()["bytes_used"]

    async def already_full(session: Any) -> int | None:  # noqa: ANN401 - AsyncSession
        del session
        return int(used)

    register_quota(already_full)
    full = await world.call(
        "POST",
        f"/knowledge/articles/{article['id']}/apply",
        a,
        a.tech_a,
        json=_apply(item),
    )
    assert problem(full) == (403, "storage_quota_exceeded")
    assert recorder.written == []
    assert (await world.sql(count, a.tenant))[0]["n"] == before


async def test_a_copy_keeps_its_thumbnail_and_stripped_metadata(
    world: World, files: FileServices
) -> None:
    del files
    a = world.a
    topic = await _topic(world, a, "Help")
    article, image = await _published_with_image(
        world, a, topic, picture=(_photo_with_gps(), "photo.jpg")
    )
    item = await world.create(a, a.admin)
    applied = await world.call(
        "POST", f"/knowledge/articles/{article['id']}/apply", a, a.tech_a, json=_apply(item)
    )
    assert applied.status_code == 200, applied.text
    copy = applied.json()["html"].split('data-file-id="')[1].split('"')[0]
    rows = await world.sql(
        "SELECT id, metadata_stripped, thumb_key IS NOT NULL AS thumb FROM files"
        " WHERE id = ANY($1::uuid[])",
        [uuid.UUID(image), uuid.UUID(copy)],
    )
    assert {(r["metadata_stripped"], r["thumb"]) for r in rows} == {(True, True)}
    thumb = await world.call("GET", f"/files/{copy}/thumbnail", a, a.tech_a)
    assert thumb.status_code == 200, thumb.text
    assert thumb.headers["content-type"] == "image/webp"


# --- save as knowledge (REQ-KB-016) --------------------------------------------------------------


async def test_a_resolution_becomes_a_draft_linked_to_its_record(world: World) -> None:
    a = world.a
    topic = await _topic(world, a, "Help")
    item = await world.create(a, a.admin, group_id=str(a.ga))
    body = {"record_type": "incident", "record_id": item["id"], "topic_id": topic["id"]}
    none = await world.call(
        "POST", "/knowledge/articles/from-record", a, a.tech_a, json=body, headers=_new()
    )
    assert problem(none) == (404, "kb_record_has_no_resolution")
    await world.sql(
        "UPDATE work_items SET resolution = $2 WHERE id = $1",
        uuid.UUID(item["id"]),
        "<p>Reset the token, then call Sara on +966 50 123 4567.</p>",
    )
    made = await world.call(
        "POST", "/knowledge/articles/from-record", a, a.tech_a, json=body, headers=_new()
    )
    assert made.status_code == 201, made.text
    out = made.json()
    draft = out["article"]["drafts"]["en"]
    assert draft["title"] == "Mail is down"
    assert "Reset the token" in draft["body_html"]
    assert out["personal_data"] == [{"field": "body", "kind": "phone"}]
    links = await world.call(
        "GET", f"/knowledge/records/incident/{item['id']}/articles", a, a.tech_a
    )
    assert [(i["article"]["id"], i["source"]) for i in links.json()["items"]] == [
        (out["article"]["id"], "created_from")
    ]
    # Someone who cannot open the incident gets "not found", and no article is made.
    hidden = await world.call(
        "POST", "/knowledge/articles/from-record", a, a.tech_b, json=body, headers=_new()
    )
    assert problem(hidden) == (404, "kb_record_has_no_resolution")
