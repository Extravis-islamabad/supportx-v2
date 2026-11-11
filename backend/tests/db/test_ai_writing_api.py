"""Writing help over HTTP (WP-038, REQ-INC-136), with the recorded fake.

- A draft or an improved text comes back for the review panel; nothing is sent or saved.
- The prompt holds only what the person may see, and their instruction. A reply never reads
  private notes, even when the admin chose them for summaries; a note does then.
- Missing input, a translation without a language, and a switched-off feature are refused;
  someone who may not open the record gets 404, and someone who may not reply is refused.
"""

from typing import Any

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_ai_summaries_api import (
    PRIVATE_NOTE,
    PUBLIC_REPLY,
    ai_settings,
    incident_with_talk,
)
from tests.db.test_incidents_api import CONSOLE, Org, World, problem

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

ALL_SOURCES = ["description", "replies", "public_notes", "private_notes"]


def path(item: dict[str, Any]) -> str:
    return f"/ai/writing/incident/{item['id']}"


async def write(world: World, org: Org, user: Any, item: dict[str, Any], **body: Any) -> Any:  # noqa: ANN401 - JSON
    return await world.call("POST", path(item), org, user, json=body, headers=CONSOLE)


async def prompts(world: World, org: Org, feature: str) -> list[str]:
    rows = await world.sql(
        "SELECT masked_input FROM ai_calls WHERE tenant_id = $1 AND feature = $2"
        " ORDER BY created_at",
        org.tenant,
        feature,
    )
    return [str(r["masked_input"]) for r in rows]


async def test_req_inc_136_a_reply_draft_never_reads_private_notes(world: World) -> None:
    a = world.a
    await ai_settings(world, a, summary_sources=ALL_SOURCES)
    item = await incident_with_talk(world, a)
    made = await write(
        world, a, a.tech_a, item, mode="draft", kind="reply", instruction="Say we are on it"
    )
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["text"].startswith("[reply_draft]")
    assert (body["model"], len(body["call_id"])) == ("fake", 36)
    (sent,) = await prompts(world, a, "reply_draft")
    assert "Outlook keeps asking" in sent  # the public reply
    assert "expired certificate" not in sent  # the private note: never for a reply
    assert "Say we are on it" in sent
    assert "@" not in sent  # display names only
    note = await write(
        world, a, a.tech_a, item, mode="draft", kind="note", instruction="Summarise for the team"
    )
    assert note.status_code == 200, note.text
    assert "expired certificate" in (await prompts(world, a, "reply_draft"))[-1]
    assert PUBLIC_REPLY  # the texts the assertions above look for
    assert PRIVATE_NOTE


async def test_req_inc_136_improving_text_and_translating(world: World) -> None:
    a = world.a
    item = await incident_with_talk(world, a)
    better = await write(
        world,
        a,
        a.tech_a,
        item,
        mode="improve",
        kind="reply",
        text="we fix it soon",
        style="formal",
    )
    assert better.status_code == 200, better.text
    (sent,) = await prompts(world, a, "text_improve")
    assert "we fix it soon" in sent
    assert "more formal" in sent
    no_language = await write(
        world, a, a.tech_a, item, mode="improve", kind="reply", text="Hello", style="translate"
    )
    assert problem(no_language) == (422, "ai_writing_language_required")
    translated = await write(
        world,
        a,
        a.tech_a,
        item,
        mode="improve",
        kind="reply",
        text="Hello",
        style="translate",
        language="ar",
    )
    assert translated.status_code == 200, translated.text
    assert "Write in Arabic" in (await prompts(world, a, "text_improve"))[-1]


async def test_missing_input_and_switches_are_refused(world: World) -> None:
    a = world.a
    item = await incident_with_talk(world, a)
    assert problem(await write(world, a, a.tech_a, item, mode="draft", kind="reply")) == (
        422,
        "ai_writing_instruction_required",
    )
    assert problem(await write(world, a, a.tech_a, item, mode="improve", kind="note")) == (
        422,
        "ai_writing_text_required",
    )
    await ai_settings(world, a, disabled_features=["reply_draft"])
    off = await write(world, a, a.tech_a, item, mode="draft", kind="reply", instruction="Hi")
    assert problem(off) == (403, "ai_feature_off")
    still = await write(world, a, a.tech_a, item, mode="improve", kind="reply", text="hi there")
    assert still.status_code == 200, still.text  # the other feature has its own switch


async def test_not_visible_is_404_and_requesters_are_refused(world: World) -> None:
    a, b = world.a, world.b
    item = await incident_with_talk(world, a)
    for org, user in ((a, a.tech_b), (b, b.admin)):
        hidden = await write(world, org, user, item, mode="draft", kind="reply", instruction="Hi")
        assert hidden.status_code == 404, hidden.text
    refused = await write(world, a, a.requester, item, mode="draft", kind="reply", instruction="Hi")
    # Refused before any prompt: the staff record is not theirs to open (404, no existence leak).
    assert refused.status_code in {403, 404}, refused.text
    assert await prompts(world, a, "reply_draft") == []
