"""Sealed values in saved-view filters (lane C's decision for #549; ADR-050).

A saved view keeps its filter as JSON. A condition on a sealed custom field would keep the value
someone searched for in plain text, so its value is stored sealed (`sx2:`, the field codec):

- **Bound to the view:** purpose `field.work_items.view_filter`, the view's row and the
  condition's field. A value copied raw into another view does not open there; "save as new"
  sends the opened value, which is sealed again for the new view.
- **Typed:** the value is sealed as JSON text, so a number or a list keeps its type; an `in`
  list is sealed item by item.
- **Opened for the owner only** (others never get a view naming a field they may not see, D-176),
  and only while the owner may read the field (ADR-047). Otherwise the condition comes back
  withheld (`value` null, `withheld` true), never as `sx2:` text. Saving the view with that
  condition untouched keeps what is stored.
- **A client never sends `sx2:`:** such a value is refused, so ciphertext cannot be moved between
  views or people.
- **Rotation:** sealed under the tenant's newest data key; a retired key still opens what it
  sealed (ADR-050 §3), so a rotation needs nothing here.
"""

import copy
import json
import uuid
from collections.abc import Iterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import FieldError, ValidationFailed
from app.modules.work_items.service import custom_values
from app.shared.crypto.codec import TEXT_PREFIX
from app.shared.fields import Binding, field_cipher_for, purpose

VIEW_FILTER = purpose(module="work_items", what="view_filter")
TABLE = "work_item_views"
WITHHELD = "withheld"
VALUED_OPS_WITHOUT_VALUE = frozenset({"is_null", "is_not_null"})


def conditions(tree: object) -> Iterator[dict[str, Any]]:
    """Every condition of a filter tree, in order (the dicts themselves, so they can be changed)."""
    if isinstance(tree, dict):
        if isinstance(tree.get("field"), str):
            yield tree
        for key in ("and", "or", "root"):
            children = tree.get(key)
            if isinstance(children, list):
                for child in children:
                    yield from conditions(child)
            elif isinstance(children, dict):
                yield from conditions(children)


def _binding(view_id: uuid.UUID, field: str) -> Binding:
    return Binding(TABLE, view_id, field)


def _is_ciphertext(value: object) -> bool:
    if isinstance(value, list):
        return any(_is_ciphertext(v) for v in value)
    return isinstance(value, str) and value.startswith(TEXT_PREFIX)


def refuse_ciphertext(tree: object) -> None:
    """422 when a client sent sealed text as a value (condition 2: never accepted from outside)."""
    for condition in conditions(tree):
        if _is_ciphertext(condition.get("value")):
            raise ValidationFailed(
                errors=[
                    FieldError(
                        field="body.filter",
                        code="view_filter_sealed_value",
                        message_key="errors.field.view_filter_sealed_value",
                        params={"field": str(condition["field"])},
                    )
                ]
            )


def _kept(before: object, field: str, op: object, nth: int) -> dict[str, Any] | None:
    """The stored condition a withheld one stands for: the nth on that field and operator."""
    found = [c for c in conditions(before) if c.get("field") == field and c.get("op") == op]
    return found[nth] if nth < len(found) else None


def restore_withheld(tree: object, before: object) -> object:
    """Put back what is stored for each condition sent back withheld (condition 3: untouched).

    Matched by field, operator and place among that field's conditions; one with nothing stored
    to stand for is refused rather than dropped silently.
    """
    if tree is None:
        return None
    restored = copy.deepcopy(tree)
    counts: dict[tuple[str, object], int] = {}
    for condition in conditions(restored):
        field, op = str(condition["field"]), condition.get("op")
        nth = counts.get((field, op), 0)
        counts[(field, op)] = nth + 1
        if not condition.pop(WITHHELD, False):
            continue
        kept = _kept(before, field, op, nth)
        if kept is None:
            raise ValidationFailed(
                errors=[
                    FieldError(
                        field="body.filter",
                        code="view_filter_withheld_unknown",
                        message_key="errors.field.view_filter_withheld_unknown",
                        params={"field": field},
                    )
                ]
            )
        condition["value"] = kept.get("value")
    return restored


async def seal(
    session: AsyncSession,
    view_id: uuid.UUID,
    tree: object,
    sealed_fields: frozenset[str],
    before: object = None,
) -> object:
    """The tree as stored: plain values of sealed fields sealed for this view.

    A value already sealed is kept, and so is a stored one whose plaintext is sent back unchanged
    (`before`, the stored filter): renaming a view does not re-seal it, so no change is recorded.
    """
    if tree is None:
        return None
    stored = copy.deepcopy(tree)
    cipher = field_cipher_for(session, custom_values.settings_of(session))
    counts: dict[tuple[str, object], int] = {}
    for condition in conditions(stored):
        field, op = str(condition["field"]), condition.get("op")
        nth = counts.get((field, op), 0)
        counts[(field, op)] = nth + 1
        value = condition.get("value")
        if (
            field not in sealed_fields
            or value is None
            or op in VALUED_OPS_WITHOUT_VALUE
            or _is_ciphertext(value)
        ):
            continue
        binding = _binding(view_id, field)
        previous = _kept(before, field, op, nth)
        if (
            previous is not None
            and _is_ciphertext(previous.get("value"))
            and await _opens_to(cipher, binding, previous["value"], value)
        ):
            condition["value"] = previous["value"]
            continue
        if isinstance(value, list):
            condition["value"] = [
                await cipher.seal(VIEW_FILTER, binding, json.dumps(item)) for item in value
            ]
        else:
            condition["value"] = await cipher.seal(VIEW_FILTER, binding, json.dumps(value))
    return stored


async def _opens_to(cipher: Any, binding: Binding, stored: object, plain: object) -> bool:  # noqa: ANN401 - the field cipher
    """Whether the stored sealed value opens to exactly the plaintext sent."""
    items = stored if isinstance(stored, list) else [stored]
    opened_items = []
    for item in items:
        text = await cipher.open(VIEW_FILTER, binding, str(item))
        if text is None:
            return False
        opened_items.append(json.loads(text))
    return (opened_items if isinstance(stored, list) else opened_items[0]) == plain


def history_value(tree: object, sealed_fields: frozenset[str]) -> object:
    """What field history keeps of a filter (condition 6).

    The tree, or only its fields' names when it names a sealed field, so no value and no `sx2:`
    text sits in history.
    """
    if not has_sealed(tree, sealed_fields):
        return tree
    return sorted({str(c["field"]) for c in conditions(tree)})


async def opened(
    session: AsyncSession,
    view_id: uuid.UUID,
    tree: object,
    withheld_fields: frozenset[str],
) -> object:
    """The tree as its owner sees it: sealed values opened, or withheld (never `sx2:` text).

    `withheld_fields`: the fields the owner may not see now (ADR-047); a value that does not open
    (moved from another view, or a key gone) is withheld too, and the codec logs the event.
    """
    if tree is None:
        return None
    shown = copy.deepcopy(tree)
    cipher = field_cipher_for(session, custom_values.settings_of(session))
    for condition in conditions(shown):
        field = str(condition["field"])
        value = condition.get("value")
        if not _is_ciphertext(value):
            continue
        if field in withheld_fields:
            condition.update({"value": None, WITHHELD: True})
            continue
        binding = _binding(view_id, field)
        items = value if isinstance(value, list) else [value]
        opened_items: list[Any] = []
        for item in items:
            text = await cipher.open(VIEW_FILTER, binding, str(item))
            if text is None:
                opened_items = []
                break
            opened_items.append(json.loads(text))
        if not opened_items:
            condition.update({"value": None, WITHHELD: True})
        else:
            condition["value"] = opened_items if isinstance(value, list) else opened_items[0]
    return shown


def for_validation(tree: object) -> Any:  # noqa: ANN401 - the filter DSL's JSON tree
    """The tree to check with the list's rules, without its sealed text.

    A condition holding sealed text (validated in plain when it was first saved) stands as
    `is_not_null` on its field, so its shape still counts and no ciphertext is checked as a value.
    """
    if tree is None:
        return None
    checked = copy.deepcopy(tree)
    for condition in conditions(checked):
        if _is_ciphertext(condition.get("value")):
            condition["op"] = "is_not_null"
            condition.pop("value", None)
    return checked


def has_sealed(tree: object, sealed_fields: frozenset[str]) -> bool:
    """Whether a filter names a sealed field (the list then wants its POST form)."""
    return any(str(c["field"]) in sealed_fields for c in conditions(tree))


def plain_sealed(tree: object, sealed_fields: frozenset[str]) -> bool:
    """Whether a stored filter still holds a sealed field's value in plain text (the job's work)."""
    for condition in conditions(tree):
        value = condition.get("value")
        if (
            str(condition["field"]) in sealed_fields
            and value is not None
            and condition.get("op") not in VALUED_OPS_WITHOUT_VALUE
            and not _is_ciphertext(value)
        ):
            return True
    return False


def as_mapping(tree: object) -> dict[str, Any] | None:
    """The tree as the view's column holds it."""
    return tree if isinstance(tree, dict) else None
