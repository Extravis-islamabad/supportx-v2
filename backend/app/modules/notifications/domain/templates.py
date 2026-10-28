"""Notification templates: sandboxed rendering and variable checks (REQ-NTF-011, architecture §6.8).

A template is a subject and a plain-text body in Jinja2 syntax, rendered in a sandbox that can
reach only the event's variables (nested mappings of strings: `record.title`,
`requester.name`). The shipped defaults are labels (`notification_template.<event>.subject` /
`.body`) in English, Arabic and Urdu, so translators work in the one dictionary.

E-mail HTML is built here from the rendered text, escaped paragraph by paragraph, plus a button
to the record; the mail foundation's `wrap_html` adds the tenant's brand around it.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from jinja2 import TemplateSyntaxError, nodes
from jinja2.sandbox import SandboxedEnvironment
from markupsafe import Markup, escape

# Plain text: the text is escaped when it becomes HTML, never before.
_ENVIRONMENT = SandboxedEnvironment(autoescape=False, keep_trailing_newline=False)
MAX_SUBJECT = 300
SYNTAX = "template_syntax"


@dataclass(frozen=True)
class Rendered:
    """One message's text in one language."""

    subject: str
    body: str


class TemplateProblemError(ValueError):
    """A template cannot be used; `code` is a label key suffix, `params` fill it."""

    def __init__(self, code: str, **params: str) -> None:
        super().__init__(code)
        self.code = code
        self.params = params


def _paths(node: nodes.Node) -> Iterator[str]:
    """Dotted variable paths a template reads (`record.title`), outermost chain only."""
    if isinstance(node, nodes.Getattr):
        chain: list[str] = [node.attr]
        inner: nodes.Node = node.node
        while isinstance(inner, nodes.Getattr):
            chain.append(inner.attr)
            inner = inner.node
        if isinstance(inner, nodes.Name):
            yield ".".join([inner.name, *reversed(chain)])
            return
    elif isinstance(node, nodes.Name) and node.ctx == "load":
        yield node.name
        return
    for child in node.iter_child_nodes():
        yield from _paths(child)


def referenced(source: str) -> set[str]:
    """Every variable path `source` reads; TemplateProblemError on a syntax error."""
    try:
        tree = _ENVIRONMENT.parse(source)
    except TemplateSyntaxError as error:
        raise TemplateProblemError(SYNTAX, line=str(error.lineno)) from None
    assigned = {target.name for target in tree.find_all(nodes.Name) if target.ctx == "store"}
    return {path for path in _paths(tree) if path.split(".", 1)[0] not in assigned}


def unknown_variables(source: str, offered: set[str]) -> list[str]:
    """Paths `source` reads that the event does not offer (REQ-NTF-011 AC2, AC3), sorted.

    A path is known when it is offered, or is an object whose fields are offered
    (`{% if record.asset %}` tests the object `record.asset` when `record.asset.name` exists).
    """
    prefixes = {name.rsplit(".", depth)[0] for name in offered for depth in range(name.count("."))}
    return sorted(p for p in referenced(source) if p not in offered and p not in prefixes)


def nest(flat: Mapping[str, object]) -> dict[str, object]:
    """{"record.title": "x"} -> {"record": {"title": "x"}}, the shape templates read."""
    tree: dict[str, object] = {}
    for path, value in flat.items():
        node = tree
        *parents, leaf = path.split(".")
        for part in parents:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                child = node[part] = {}
            node = child
        node[leaf] = value
    return tree


def render(subject: str, body: str, variables: Mapping[str, object]) -> Rendered:
    """Both parts filled in; a missing value renders empty, never as a code or an error."""
    context = nest({k: "" if v is None else v for k, v in variables.items()})
    try:
        rendered_subject = _ENVIRONMENT.from_string(subject).render(context)
        rendered_body = _ENVIRONMENT.from_string(body).render(context)
    except TemplateSyntaxError as error:
        raise TemplateProblemError(SYNTAX, line=str(error.lineno)) from None
    one_line = " ".join(rendered_subject.split())[:MAX_SUBJECT]
    return Rendered(one_line, rendered_body.strip())


def html_body(body: str, *, link: str, link_text: str, colour: str) -> Markup:
    """The rendered text as escaped HTML paragraphs, with a button to the record."""
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    parts = [
        Markup('<p style="margin:0 0 12px;">{}</p>').format(
            Markup("<br>").join(escape(line) for line in paragraph.splitlines())
        )
        for paragraph in paragraphs
    ]
    parts.append(
        Markup(
            '<p style="margin:20px 0 0;"><a href="{}" style="display:inline-block;'
            "padding:10px 18px;background:{};color:#ffffff;text-decoration:none;"
            'border-radius:6px;">{}</a></p>'
        ).format(link, colour, link_text)
    )
    return Markup("").join(parts)
