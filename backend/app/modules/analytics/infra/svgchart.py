"""A small SVG chart for PDF exports (REQ-RPT-058: the PDF includes the chart).

Bar, line and doughnut in the same palette order as the console's chart kit, so a printed chart
reads like the screen. Pure Python with no browser and no Node; every label is XML-escaped, and
the SVG is inlined into the PDF's HTML, so it never needs a URL. Right-to-left mirrors the
category axis like the console (REQ-DSH-046).
"""

import math
from xml.sax.saxutils import escape

PALETTE = ("#1677ff", "#13a8a8", "#52c41a", "#faad14", "#f5222d", "#722ed1", "#eb2f96", "#8c8c8c")
WIDTH = 640
HEIGHT = 280
LABEL_MAX = 14


def _short(text: str) -> str:
    return text if len(text) <= LABEL_MAX else f"{text[: LABEL_MAX - 1]}…"


def _bars(categories: list[str], values: list[float], *, rtl: bool, line: bool) -> list[str]:
    top = max([*values, 0.0]) or 1.0
    left, bottom, plot_w, plot_h = 40, HEIGHT - 50, WIDTH - 60, HEIGHT - 80
    count = max(len(values), 1)
    step = plot_w / count
    parts = [
        f'<line x1="{left}" y1="{bottom}" x2="{left + plot_w}" y2="{bottom}" stroke="#bfbfbf"/>'
    ]
    points: list[str] = []
    for index, (name, value) in enumerate(zip(categories, values, strict=True)):
        slot = count - 1 - index if rtl else index
        x = left + slot * step
        h = plot_h * value / top
        if line:
            points.append(f"{x + step / 2:.1f},{bottom - h:.1f}")
        else:
            parts.append(
                f'<rect x="{x + step * 0.15:.1f}" y="{bottom - h:.1f}" width="{step * 0.7:.1f}" '
                f'height="{h:.1f}" fill="{PALETTE[0]}"/>'
            )
        parts.append(
            f'<text x="{x + step / 2:.1f}" y="{bottom - h - 4:.1f}" font-size="10" '
            f'text-anchor="middle">{escape(f"{value:g}")}</text>'
        )
        parts.append(
            f'<text x="{x + step / 2:.1f}" y="{bottom + 14}" font-size="9" '
            f'text-anchor="middle">{escape(_short(name))}</text>'
        )
    if line and points:
        parts.append(
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{PALETTE[0]}" '
            'stroke-width="2"/>'
        )
    return parts


def _doughnut(categories: list[str], values: list[float], *, rtl: bool) -> list[str]:
    total = sum(values) or 1.0
    cx, cy, outer, inner = 140, HEIGHT / 2, 110, 60
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
    legend_x = 40 if rtl else 300
    for index, (name, value) in enumerate(zip(categories, values, strict=True)):
        y = 30 + index * 18
        if y > HEIGHT - 10:
            break
        parts.append(
            f'<rect x="{legend_x}" y="{y - 9}" width="10" height="10" '
            f'fill="{PALETTE[index % len(PALETTE)]}"/>'
        )
        parts.append(
            f'<text x="{legend_x + 16}" y="{y}" font-size="10">'
            f"{escape(_short(name))}: {escape(f'{value:g}')}</text>"
        )
    return parts


def chart_svg(kind: str, categories: list[str], values: list[float | None], *, rtl: bool) -> str:
    """The chart as an inline SVG element (empty values count as 0)."""
    numbers = [v or 0.0 for v in values]
    if kind == "doughnut":
        parts = _doughnut(categories, numbers, rtl=rtl)
    else:
        parts = _bars(categories, numbers, rtl=rtl, line=kind in {"line", "area"})
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img">{"".join(parts)}</svg>'
    )
