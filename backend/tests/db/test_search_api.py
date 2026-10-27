"""Search and record pickers (WP-027, REQ-INC-085, ADR-029, D-085) against real PostgreSQL.

Search must respect permissions exactly like the lists (D-052), find word forms in Arabic and
Urdu without diacritics, tolerate typos and partial words, and tell people apart by email.
"""

import uuid
from typing import Any

import pytest

from app.shared.search import normalize, words
from conftest import assign_system_role
from tests.db.test_incidents_api import BASE, Org, World, ids, role, world
from tests.db.test_users_api import seed_users

__all__ = ["world"]  # fixture, re-used

pytestmark = pytest.mark.db

SEARCH = f"{BASE}/search"


async def search(
    world: World,
    org: Org,
    user: uuid.UUID,
    q: str | None = None,
    **params: Any,  # noqa: ANN401 - query parameters
) -> list[dict[str, Any]]:
    if q is not None:
        params["q"] = q
    response = await world.call("GET", SEARCH, org, user, params=params)
    assert response.status_code == 200, response.text
    return list(response.json()["items"])


def found(rows: list[dict[str, Any]]) -> list[str]:
    return [row["id"] for row in rows]


async def person(world: World, org: Org, name: str, email: str) -> uuid.UUID:
    (user,) = await seed_users(
        world.db, org.tenant, [{"user_type": "requester", "display_name": name, "email": email}]
    )
    await assign_system_role(world.db.admin_url, org.tenant, user, "requester")
    return user


CORPUS = [
    "Printer on floor 3 is DOWN",
    "Café crème — naïve résumé",
    "أَحْمَد يطلب طابعةً جديدة",
    "إحمد آلة ٱلطباعة لا تعمل",
    "كمبيوتر المكتب ١٢٣",
    "کمپیوٹروں میں مسئلہ ہے، ۴۵۶",
    "ہمارے دفتر کی بجلی بند ہے",
    "ﻻ ﺗﻌﻤﻞ",  # Arabic presentation forms
    "zero\u200bwidth‌join‍",
]


async def test_database_and_python_normalise_alike(world: World) -> None:
    """One rule set, two places (migration 0020 and app/shared/search/domain.py)."""
    for text in CORPUS:
        (row,) = await world.sql("SELECT sx_search_normalize($1) AS n", text)
        assert row["n"] == normalize(text), text
    assert words("أَحْمَد") == words("احمد") == words("إحمد")
    assert words("كمپيوٹر") == words("کمپیوٹر")  # Arabic kaf and yeh typed for the Urdu letters
    assert words("INC-١٢") == ["inc", "12"]


async def test_req_inc_085_ac1_display_id_whatever_status_or_assignee(world: World) -> None:
    a = world.a
    other = await world.create(
        a, a.admin, subject="Unrelated", group_id=str(a.gb), technician_id=str(a.tech_b)
    )
    resolved = await world.act(a, a.admin, other, "resolve")
    assert resolved.status_code == 200, resolved.text
    closed = await world.act(a, a.admin, resolved.json(), "close")
    assert closed.status_code == 200, closed.text
    number = other["display_id"].split("-")[1]
    arabic_digits = number.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
    for typed in (other["display_id"], other["display_id"].lower(), number, f"INC-{arabic_digits}"):
        rows = await search(world, a, a.lead, typed)
        assert found(rows)[:1] == [other["id"]], typed
    # The picker finds it in any state; a narrower status filter still applies when asked for.
    assert found(await search(world, a, a.lead, number, status_category="open")) == []


async def test_req_inc_085_ac2_subject_words_ranked_typos_and_parts(world: World) -> None:
    a = world.a
    both = await world.create(a, a.admin, subject="Printer on floor 3 is down")
    one = await world.create(a, a.admin, subject="Printer toner is low")
    body = await world.create(
        a,
        a.admin,
        subject="Floor 3 request",
        description="<p>The <b>printers</b> jam &amp; smudge</p>",
    )
    await world.create(a, a.admin, subject="Mail is down")
    rows = found(await search(world, a, a.lead, "printer down"))
    assert rows[0] == both["id"]
    assert one["id"] not in rows  # every word must match
    assert set(found(await search(world, a, a.lead, "printers"))) == {
        both["id"],
        one["id"],
        body["id"],
    }  # English word forms, in the subject (ranked first) and the description
    assert found(await search(world, a, a.lead, "printers"))[-1] == body["id"]
    assert {both["id"], one["id"]} <= set(found(await search(world, a, a.lead, "printr")))  # typo
    assert {both["id"], one["id"]} <= set(found(await search(world, a, a.lead, "prin")))  # part
    assert found(await search(world, a, a.lead, "smudge")) == [body["id"]]
    assert found(await search(world, a, a.lead, "amp")) == []  # entities are not words


async def test_req_inc_085_ac3_never_outside_the_users_scope(world: World) -> None:
    """The same records as the list, for every kind of visibility (D-052, D-068)."""
    a = world.a
    subject = "Projector flickers"
    made = {
        "my_group": await world.create(
            a, a.admin, subject=subject, group_id=str(a.ga), requester_id=str(a.requester2)
        ),
        "assigned_to_me": await world.create(
            a,
            a.admin,
            subject=subject,
            group_id=str(a.gb),
            technician_id=str(a.tech_a),
            requester_id=str(a.requester2),
        ),
        "my_site_queue": await world.create(a, a.admin, subject=subject),
        "other_site_queue": await world.create(
            a, a.admin, subject=subject, requester_id=str(a.requester2)
        ),
        "other_group": await world.create(
            a, a.admin, subject=subject, group_id=str(a.gb), requester_id=str(a.requester2)
        ),
    }
    other_tenant = await world.create(world.b, world.b.admin, subject=subject)
    by_id = {item["id"]: name for name, item in made.items()}
    for user in (a.tech_a, a.tech_b, a.tech_c, a.lead):
        listed = await ids(world, a, user, "?view=all")
        searched = set(found(await search(world, a, user, "projector")))
        assert searched == {i for i in listed if i in by_id}, (user, searched)
        assert other_tenant["id"] not in searched
        # The ID too: never a way around the scope.
        for item in made.values():
            hits = found(await search(world, a, user, item["display_id"]))
            assert (item["id"] in hits) == (item["id"] in listed)
    assert {by_id[i] for i in found(await search(world, a, a.tech_a, "projector"))} == {
        "my_group",
        "assigned_to_me",
        "my_site_queue",
    }
    # Without view permission at all (a requester in the console API): refused like the list.
    response = await world.call("GET", SEARCH, a, a.requester, params={"q": "projector"})
    as_list = await world.call("GET", BASE, a, a.requester)
    assert response.status_code == as_list.status_code


async def test_arabic_word_forms_without_diacritics(world: World) -> None:
    a = world.a
    printers = await world.create(a, a.admin, subject="الطابعات لا تعمل في المكتب")
    hamza = await world.create(a, a.admin, subject="إعادة تعيين كلمة المرور")
    for typed in ("طابعة", "الطابعة", "طَابِعَة", "طابعات"):
        assert printers["id"] in found(await search(world, a, a.lead, typed)), typed
    for typed in ("اعادة", "إعادة", "أعادة"):  # hamza forms typed any way
        assert hamza["id"] in found(await search(world, a, a.lead, typed)), typed
    assert hamza["id"] in found(await search(world, a, a.lead, "كلمه المرور"))  # teh marbuta


async def test_urdu_word_forms_by_prefix_and_letter_variants(world: World) -> None:
    a = world.a
    computers = await world.create(a, a.admin, subject="کمپیوٹروں میں مسئلہ ہے")
    power = await world.create(a, a.admin, subject="ہمارے دفتر کی بجلی بند ہے")
    assert computers["id"] in found(await search(world, a, a.lead, "کمپیوٹر"))  # plural form
    assert computers["id"] in found(await search(world, a, a.lead, "كمپيوٹر"))  # Arabic kaf, yeh
    assert computers["id"] in found(await search(world, a, a.lead, "مسئله"))  # heh variants
    assert power["id"] in found(await search(world, a, a.lead, "دفتر بجلی"))
    assert power["id"] not in found(await search(world, a, a.lead, "دفتر پانی"))


async def test_by_requester_name_and_email(world: World) -> None:
    a = world.a
    ahmed = await person(world, a, "Ahmed Khan", "ahmed.khan@alpha.test")
    other = await person(world, a, "Bilal Raza", "bilal@alpha.test")
    his = await world.create(a, a.admin, subject="Laptop battery", requester_id=str(ahmed))
    theirs = await world.create(a, a.admin, subject="Laptop screen", requester_id=str(other))
    for typed in ("ahmed", "Ahm", "ahmd khan", "ahmed.khan"):
        hits = found(await search(world, a, a.lead, typed))
        assert his["id"] in hits, typed
        assert theirs["id"] not in hits, typed
    # Narrowed to one requester (the picker's "same requester" group).
    assert found(await search(world, a, a.lead, requester_id=str(ahmed))) == [his["id"]]


async def test_recent_ids_keep_the_scope(world: World) -> None:
    a = world.a
    mine = await world.create(a, a.admin, subject="Recent one", group_id=str(a.ga))
    hidden = await world.create(a, a.admin, subject="Recent two", group_id=str(a.gb))
    rows = await search(world, a, a.tech_a, ids=[mine["id"], hidden["id"]])
    assert found(rows) == [mine["id"]]


async def test_people_search_names_typos_and_arabic(world: World) -> None:
    """Pickers show people they can tell apart; search finds them however they are typed."""
    a = world.a
    first = await person(world, a, "Mohammed Al-Hashimi", "m.hashimi@alpha.test")
    second = await person(world, a, "Mohammed Al-Hashimi", "mohammed.h@alpha.test")
    arabic = await person(world, a, "أحمد علي", "ahmed.ali@alpha.test")
    urdu = await person(world, a, "عائشہ صدیقی", "ayesha@alpha.test")

    async def users(q: str) -> set[str]:
        response = await world.call("GET", "/users", a, a.admin, params={"q": q, "limit": 50})
        assert response.status_code == 200, response.text
        return {row["id"] for row in response.json()["items"]}

    assert {str(first), str(second)} <= await users("mohammed")
    assert {str(first), str(second)} <= await users("Moham")  # half a name
    assert {str(first), str(second)} <= await users("Mohamed")  # a common misspelling
    assert await users("hashimi") >= {str(first), str(second)}
    assert str(second) in await users("mohammed.h")  # by email
    assert str(first) not in await users("mohammed.h@")
    assert str(arabic) in await users("احمد")  # without the hamza
    assert str(arabic) in await users("أحمد")
    assert str(urdu) in await users("عایشه")  # Urdu yeh and heh typed as Arabic letters
    assert await users("zzzz") == set()
    assert await users("%%") == set()  # nothing searchable typed: nobody, not everybody
    # Assignee picker: the same search.
    response = await world.call("GET", f"{BASE}/assignees", a, a.lead, params={"search": "Tech"})
    assert response.status_code == 200, response.text
    assert {a.tech_a, a.tech_b} <= {uuid.UUID(p["id"]) for p in response.json()}


async def test_search_is_tenant_isolated_at_the_database(world: World) -> None:
    """RLS: the search columns add nothing another tenant can reach."""
    a, b = world.a, world.b
    await world.create(b, b.admin, subject="Beta secret printer")
    assert found(await search(world, a, a.lead, "secret")) == []
    wide = await role(world, a, "Wide search", [("incidents.view", "all")])
    assert (
        await world.call("PUT", f"/users/{a.tech_b}/roles/{wide}", a, a.admin)
    ).status_code == 204
    assert found(await search(world, a, a.tech_b, "secret")) == []


async def test_custom_field_text_is_searchable_and_follows_edits(world: World) -> None:
    """WP-026 (ADR-030): free text in custom fields is part of the record's search body."""
    a = world.a
    for body in (
        {"entity": "incident", "field_type": "text", "labels": {"en": "Asset tag"}},
        {
            "entity": "incident",
            "field_type": "choice",
            "labels": {"en": "Floor"},
            "choices": [{"labels": {"en": "Basement"}}],
        },
    ):
        made = await world.call("POST", "/custom-fields", a, a.admin, json=body)
        assert made.status_code == 201, made.text
    item = await world.create(
        a,
        a.admin,
        subject="Laptop broken",
        custom={"asset_tag": "bluefin laptop", "floor": "basement"},
    )
    assert found(await search(world, a, a.lead, "bluefin")) == [item["id"]]
    assert found(await search(world, a, a.lead, "basement")) == []  # choice codes are not text
    edited = await world.patch(a, a.admin, item, custom={"asset_tag": "kestrel desk"})
    assert edited.status_code == 200, edited.text
    assert found(await search(world, a, a.lead, "kestrel")) == [item["id"]]
    assert found(await search(world, a, a.lead, "bluefin")) == []
    # Subject and description still count as before.
    assert item["id"] in found(await search(world, a, a.lead, "laptop"))
