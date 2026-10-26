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


def test_c4_blocked_link_is_kept_as_plain_text() -> None:
    """QA C4: a link whose address is refused keeps its words, never a dead underlined link."""
    clean = sanitize_html('<p>See <a href="javascript:alert(1)">the manual</a> now</p>')
    assert clean == "<p>See the manual now</p>"
    assert sanitize_html("<p><a>bare</a></p>") == "<p>bare</p>"
    kept = (
        '<p><a href="https://example.com" target="_blank" '
        'rel="noopener noreferrer nofollow">ok</a></p>'
    )
    assert sanitize_html(kept) == kept


def test_wp020b_editor_formatting_survives_and_free_styles_do_not() -> None:
    """Alignment, indent, palette colours, highlights and mentions are codes, never styles."""
    editor = (
        '<h3 data-align="end" data-indent="1">T</h3><p data-align="justify" data-indent="6">'
        '<span data-color="brand">b</span><mark data-color="pink">h</mark>'
        '<span data-type="mention" data-id="0192a1b2-0000-7000-8000-000000000001" '
        'data-label="Ali">@Ali</span></p>'
    )
    assert sanitize_html(editor) == editor
    dirty = (
        '<p data-align="left" data-indent="9" style="font-size:40px">'
        '<span data-color="#ff0000" style="font-family:Comic">x</span>'
        '<mark data-color="black">y</mark><span data-type="link" data-id="x">z</span></p>'
    )
    assert sanitize_html(dirty) == "<p><span>x</span><mark>y</mark><span>z</span></p>"
