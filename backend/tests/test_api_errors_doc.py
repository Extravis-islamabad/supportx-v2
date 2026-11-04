"""`make api-errors` lists every error code with its English text (WP-041, REQ-INT-025)."""

from tooling.api_errors import render


def test_every_code_and_field_code_is_listed_with_its_text() -> None:
    labels = {
        "en": {
            "errors.api_key_revoked": "This API key has been revoked.",
            "errors.version_conflict": "Someone else changed this | reload.",
            "errors.field.missing": "This field is required.",
            "actions.save": "Save",
        }
    }
    page = render(labels)
    assert "| `api_key_revoked` | This API key has been revoked. |" in page
    assert "| `version_conflict` | Someone else changed this \\| reload. |" in page
    assert "| `missing` | This field is required. |" in page
    assert "actions.save" not in page
    assert "Save" not in page.split("## Field errors")[1]
