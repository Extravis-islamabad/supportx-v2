"""Every placeholder in an error label is filled from the params sent (QA WP-029 BUG-01).

The UI renders `errors.<code>` (and `errors.field.<code>`) with the problem's params; a label that
names `{{message}}` while a raise site sends no `message` shows the raw placeholder. This reads
every raise site in the application code (an error class or `code="..."` with a literal `params`
dict) and checks the labels of all three languages against it. Raise sites whose params are built
at run time cannot be read here; their services test the problem they send.
"""

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass

from app.core import errors
from tests.test_error_labels import APP_DIR, RESOURCES, _import_application, _subclasses

_ENTRY = re.compile(r"^\s*'([^']+)':\s*((?:'(?:[^'\\]|\\.)*'\s*\+?\s*)+),?$", re.MULTILINE)
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
LOCALES = ("en", "ar", "ur")


def label_placeholders(locale: str) -> dict[str, set[str]]:
    """`errors.*` key → the placeholders its label uses (multi-line entries joined)."""
    text = (RESOURCES / f"{locale}.ts").read_text(encoding="utf-8")
    found: dict[str, set[str]] = {}
    for key, value in _ENTRY.findall(text):
        if key.startswith("errors."):
            names = set(_PLACEHOLDER.findall(value))
            if names:
                found[key] = names
    return found


@dataclass(frozen=True)
class RaiseSite:
    where: str
    key: str
    params: frozenset[str] | None  # None: built at run time, not readable here


def _class_codes() -> dict[str, str]:
    _import_application()
    return {cls.__name__: cls.code for cls in _subclasses(errors.AppError)}


def _literal_keys(node: ast.expr | None) -> frozenset[str] | None:
    if node is None:
        return frozenset()
    if isinstance(node, ast.Dict) and all(
        isinstance(key, ast.Constant) and isinstance(key.value, str) for key in node.keys
    ):
        return frozenset(str(key.value) for key in node.keys if isinstance(key, ast.Constant))
    return None


def _name_of(node: ast.AST) -> str | None:
    return _name(node.func) if isinstance(node, ast.Call) else None


def _name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _text(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _field_problem(
    node: ast.AST, field_codes: set[str]
) -> tuple[str, frozenset[str] | None] | None:
    """A field problem written as data: `(field, code, {params})`, `Problem(field, code, {...})`,
    `problem(field, code, **params)` or `...(field=..., field_code=code, **params)`."""
    if isinstance(node, ast.Tuple) and len(node.elts) in (2, 3):
        code = _text(node.elts[1])
        if code in field_codes:
            # A pair's params may come from a side table (field → params): not readable here.
            return code, _literal_keys(node.elts[2]) if len(node.elts) == 3 else None
    if isinstance(node, ast.Call):
        keywords = {k.arg: k.value for k in node.keywords if k.arg is not None}
        named = frozenset(keywords) - {"field", "field_code", "code"}
        dynamic = any(k.arg is None for k in node.keywords)
        code = _text(keywords.get("field_code"))
        if code is None and len(node.args) >= 2:
            code = _text(node.args[1])
        if code not in field_codes:
            return None
        if len(node.args) >= 3:
            keys = _literal_keys(node.args[2])
            return code, None if keys is None or dynamic else keys | named
        return code, None if dynamic else named
    return None


def raise_sites() -> Iterator[RaiseSite]:
    classes = _class_codes()
    field_codes = {
        key.removeprefix("errors.field.")
        for key in label_placeholders("en")
        if key.startswith("errors.field.")
    }
    for source in sorted(APP_DIR.rglob("*.py")):
        if "tests" in source.parts:
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            data = None if _name_of(node) == "FieldError" else _field_problem(node, field_codes)
            if data is not None:
                yield RaiseSite(
                    where=f"{source.relative_to(APP_DIR.parent)}:{getattr(node, 'lineno', 0)}",
                    key=f"errors.field.{data[0]}",
                    params=data[1],
                )
                continue
            if not isinstance(node, ast.Call):
                continue
            name = _name(node.func)
            keywords = {k.arg: k.value for k in node.keywords if k.arg is not None}
            code_node = keywords.get("code")
            code = (
                code_node.value
                if isinstance(code_node, ast.Constant) and isinstance(code_node.value, str)
                else None
            )
            if name == "FieldError":
                prefix = "errors.field."
            elif name in classes:
                prefix = "errors."
                code = code or classes[name]
            else:
                continue
            if code is None:
                continue
            yield RaiseSite(
                where=f"{source.relative_to(APP_DIR.parent)}:{node.lineno}",
                key=f"{prefix}{code}",
                params=_literal_keys(keywords.get("params")),
            )


def test_raise_sites_are_read() -> None:
    keys = {site.key for site in raise_sites()}
    assert {"errors.rule_refused", "errors.version_conflict"} <= keys


def test_bug_01_every_error_label_placeholder_is_sent_in_params() -> None:
    labels = {locale: label_placeholders(locale) for locale in LOCALES}
    unfilled: list[str] = []
    for site in raise_sites():
        if site.params is None:
            continue
        for locale in LOCALES:
            missing = labels[locale].get(site.key, set()) - site.params
            if missing:
                unfilled.append(f"{site.where} {site.key} ({locale}): {sorted(missing)}")
    assert unfilled == [], "labels name params these raise sites do not send:\n" + "\n".join(
        unfilled
    )


def test_bug_01_label_placeholders_are_read_from_multi_line_entries() -> None:
    assert label_placeholders("en")["errors.rule_refused"] == {"message"}
    assert label_placeholders("ar")["errors.rule_refused"] == {"message_ar"}


def test_bug_01_check_finds_a_missing_param() -> None:
    site = RaiseSite("x.py:1", "errors.rule_refused", frozenset({"rule"}))
    assert label_placeholders("en")[site.key] - (site.params or frozenset()) == {"message"}
