"""A small chart for PDF exports (REQ-RPT-058: the PDF includes the chart).

Bar, line and doughnut in the same palette order as the console's chart kit, so a printed chart
reads like the screen. Pure Python with no browser and no Node.

Shapes and numbers are SVG; **every word is HTML** with an explicit direction (QA WP-035
BUG-02). WeasyPrint draws SVG `<text>` glyph by glyph, left to right, without shaping, so Arabic
category names came out with their letters reversed; HTML text goes through Pango (shaping and
bidi). Right-to-left mirrors the category axis like the console (REQ-DSH-046). Long names are
shortened in the middle, so two names that differ at the end stay apart (BUG-06); the table
below the chart always has them in full. One measure needs no legend (BUG-03).
"""

import math
from xml.sax.saxutils import escape

PALETTE = ("#1677ff", "#13a8a8", "#52c41a", "#faad14", "#f5222d", "#722ed1", "#eb2f96", "#8c8c8c")
WIDTH = 640
HEIGHT = 230
LEFT = 40  # room for the value axis
PLOT_W = WIDTH - 60
LABEL_MAX = 24


def short(text: str, limit: int = LABEL_MAX) -> str:
    """`text` cut in the middle to at most `limit` characters ("QA35 789…ha Beta")."""
    if len(text) <= limit:
        return text
    head = (limit - 1) // 2
    tail = limit - 1 - head
    return f"{text[:head]}…{text[-tail:]}"


def _word(text: str) -> str:
    """A name inside a chart: escaped and isolated, so its own direction wins."""
    return f'<bdi title="{escape(text, {chr(34): "&quot;"})}">{escape(short(text))}</bdi>'


def _bars(values: list[float], *, rtl: bool, line: bool) -> str:
    top = max([*values, 0.0]) or 1.0
    bottom, plot_h = HEIGHT - 10, HEIGHT - 40
    count = max(len(values), 1)
    step = PLOT_W / count
    parts = [
        f'<line x1="{LEFT}" y1="{bottom}" x2="{LEFT + PLOT_W}" y2="{bottom}" stroke="#bfbfbf"/>'
    ]
    points: list[str] = []
    for index, value in enumerate(values):
        slot = count - 1 - index if rtl else index
        x = LEFT + slot * step
        h = plot_h * value / top
        if line:
            points.append(f"{x + step / 2:.1f},{bottom - h:.1f}")
        else:
            parts.append(
                f'<rect x="{x + step * 0.15:.1f}" y="{bottom - h:.1f}" width="{step * 0.7:.1f}" '
                f'height="{h:.1f}" fill="{PALETTE[0]}"/>'
            )
        # Digits only in SVG: they need no shaping and read left to right in every language.
        parts.append(
            f'<text x="{x + step / 2:.1f}" y="{bottom - h - 4:.1f}" font-size="10" '
            f'text-anchor="middle">{escape(f"{value:g}")}</text>'
        )
    if line and points:
        parts.append(
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{PALETTE[0]}" '
            'stroke-width="2"/>'
        )
    return _svg(parts)


def _doughnut(values: list[float]) -> str:
    total = sum(values) or 1.0
    cx, cy, outer, inner = 110, HEIGHT / 2, 100, 55
    parts: list[str] = []
    angle = -math.pi / 2
    for index, value in enumerate(values):
        sweep = 2 * math.pi * value / total
        if sweep <= 0:
            continue
        end = angle + min(sweep, 2 * math.pi - 1e-6)
        large = 1 if sweep > math.pi else 0
        points = [
            (cx + outer * math.cos(angle), cy + outer * math.sin(angle)),
            (cx + outer * math.cos(end), cy + outer * math.sin(end)),
            (cx + inner * math.cos(end), cy + inner * math.sin(end)),
            (cx + inner * math.cos(angle), cy + inner * math.sin(angle)),
        ]
        (x1, y1), (x2, y2), (x3, y3), (x4, y4) = points
        parts.append(
            f'<path d="M{x1:.1f},{y1:.1f} A{outer},{outer} 0 {large} 1 {x2:.1f},{y2:.1f} '
            f'L{x3:.1f},{y3:.1f} A{inner},{inner} 0 {large} 0 {x4:.1f},{y4:.1f} Z" '
            f'fill="{PALETTE[index % len(PALETTE)]}"/>'
        )
        angle = end
    return _svg(parts, width=2 * cx)


def _svg(parts: list[str], width: int = WIDTH) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{HEIGHT}" '
        f'viewBox="0 0 {width} {HEIGHT}" role="img" aria-hidden="true">{"".join(parts)}</svg>'
    )


def chart_svg(kind: str, values: list[float | None], *, rtl: bool) -> str:
    """The chart's shapes and numbers (no words) as an inline SVG element."""
    numbers = [v or 0.0 for v in values]
    if kind == "doughnut":
        return _doughnut(numbers)
    return _bars(numbers, rtl=rtl, line=kind in {"line", "area"})


def chart_html(
    kind: str,
    categories: list[str],
    values: list[float | None],
    *,
    rtl: bool,
    series_name: str,
) -> str:
    """The chart for the PDF: SVG shapes, and the names as HTML in the report's direction.

    Bars and lines get a category row under the plot, slot for slot (mirrored in right to
    left, like the bars). A doughnut gets a list of its slices with their colours and values.
    One measure (`series_name`) needs no legend: the caption under the chart names it.
    """
    direction = "rtl" if rtl else "ltr"
    svg = chart_svg(kind, values, rtl=rtl)
    if kind == "doughnut":
        items = "".join(
            f'<li><span class="swatch" style="background:{PALETTE[i % len(PALETTE)]}"></span>'
            f"{_word(name)} <bdi>{escape(f'{value or 0:g}')}</bdi></li>"
            for i, (name, value) in enumerate(zip(categories, values, strict=True))
        )
        body = f'<div class="pie">{svg}<ul class="slices" dir="{direction}">{items}</ul></div>'
    else:
        # The category row sits under the plot area (the value axis keeps its room on the left
        # in both directions: the SVG mirrors the slots, not the axis).
        cells = "".join(f'<span class="cat">{_word(name)}</span>' for name in categories)
        body = (
            f'{svg}<div class="cats" dir="{direction}" '
            f'style="margin-left:{LEFT}px;width:{PLOT_W}px">{cells}</div>'
        )
    return (
        f'<figure class="chart" dir="{direction}">{body}'
        f"<figcaption><bdi>{escape(series_name)}</bdi></figcaption></figure>"
    )
