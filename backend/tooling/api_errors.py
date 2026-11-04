"""`make api-errors`: the API's error codes with their English text (WP-041, REQ-INT-025).

Written to docs/_build/api/errors.md (not committed, like the other rendered views of D-123):
integrators get the list of stable machine codes, read from the same labels the screens use
(backend/app/shared/labels/resources.json, which `make generated` writes). Field errors
(`errors.field.<code>`) are listed under the codes they belong with.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LABELS = REPO / "backend" / "app" / "shared" / "labels" / "resources.json"
TARGET = REPO / "docs" / "_build" / "api" / "errors.md"


def render(labels: dict[str, dict[str, str]]) -> str:
    """The Markdown page: one row per code, field-level codes in a second table."""
    english = labels["en"]
    codes = sorted(
        k.removeprefix("errors.")
        for k in english
        if k.startswith("errors.") and not k.startswith("errors.field.")
    )
    fields = sorted(
        k.removeprefix("errors.field.") for k in english if k.startswith("errors.field.")
    )

    def cell(text: str) -> str:
        return text.replace("|", "\\|").replace("\n", " ")

    lines = [
        "# API error codes",
        "",
        "Every error is an RFC 9457 problem with a stable `code` (docs/api/README.md). The text",
        "is the English label the screens show; `{{name}}` parts are filled from `params`.",
        "",
        "| Code | Meaning |",
        "|---|---|",
        *(f"| `{c}` | {cell(english['errors.' + c])} |" for c in codes),
        "",
        "## Field errors",
        "",
        "In `errors[]`, each with the `field` it is about.",
        "",
        "| Code | Meaning |",
        "|---|---|",
        *(f"| `{c}` | {cell(english['errors.field.' + c])} |" for c in fields),
        "",
    ]
    return "\n".join(lines)


def main() -> int:  # pragma: no cover - thin CLI over the tested render
    """Write the page."""
    if not LABELS.exists():
        sys.stderr.write("api-errors: run `make generated` first (resources.json is generated)\n")
        return 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render(json.loads(LABELS.read_text(encoding="utf-8"))), encoding="utf-8")
    sys.stdout.write(f"api-errors: wrote {TARGET.relative_to(REPO)}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
