"""Server-side rich-text sanitising (REQ-INC-064; architecture.md §11.4; D-051)."""

from app.shared.richtext import ALLOWED_TAGS, is_blank, sanitize_html


def test_req_inc_064_ac1_script_and_handlers_stripped() -> None:
    dirty = (
        '<p onclick="steal()">Hi <a href="javascript:alert(1)">x</a></p>'
        "<script>alert(1)</script><style>p{}</style><iframe src=x></iframe>"
        '<img src=x onerror="alert(1)"><p style="color:red">styled</p>'
    )
    clean = sanitize_html(dirty)
    for bad in (
        "onclick",
        "javascript:",
        "<script",
        "alert",
        "<style",
        "<iframe",
        "<img",
        "style=",
    ):
        assert bad not in clean, bad
    assert "Hi" in clean
    assert "styled" in clean


def test_req_inc_064_ac3_direction_and_arabic_text_are_kept() -> None:
    text = '<p dir="rtl">مرحبا Mail server</p><p dir="sideways">x</p>'
    clean = sanitize_html(text)
    assert '<p dir="rtl">مرحبا Mail server</p>' in clean
    assert "sideways" not in clean


def test_req_inc_064_editor_output_survives_unchanged() -> None:
    """What the editor produces (StarterKit, link, table) round-trips exactly."""
    editor = (
        "<h2>Steps</h2><ol><li><p>Restart</p></li></ol><p><strong>b</strong> <em>i</em> "
        "<u>u</u> <s>s</s> <code>c</code></p><pre><code>log</code></pre><blockquote><p>q</p>"
        '</blockquote><hr><p><a href="https://example.com" target="_blank" '
        'rel="noopener noreferrer nofollow">link</a></p><table><tbody><tr>'
        '<th colspan="1" rowspan="1"><p>h</p></th></tr><tr><td colspan="1" rowspan="1"><p>d</p>'
        "</td></tr></tbody></table>"
    )
    assert sanitize_html(editor) == editor
    assert {"table", "a", "pre", "u"} <= ALLOWED_TAGS


def test_blank_editor_output() -> None:
    assert is_blank("<p></p>")
    assert is_blank(" <p> </p><br> ")
    assert not is_blank("<p>x</p>")
