import { describe, expect, it } from 'vitest';

import { withTokenColours } from './themeColours';

const COLOURS = { text: '#eee', secondary: '#bbb', line: '#555', grid: '#333' };

describe('QA9-V-03: chart text and lines take the theme colours', () => {
  it('fills axis labels, lines and the legend, and keeps what the chart set', () => {
    const out = withTokenColours(
      {
        xAxis: { type: 'category', axisLabel: { formatter: 'x' } },
        yAxis: [{ type: 'value' }, { type: 'value', axisLabel: { color: '#f00' } }],
        legend: { bottom: 0 },
      },
      COLOURS,
    ) as Record<string, unknown>;
    const x = out.xAxis as Record<string, Record<string, unknown>>;
    expect(x.axisLabel).toEqual({ color: '#bbb', formatter: 'x' });
    expect(x.axisLine).toEqual({ lineStyle: { color: '#555' } });
    const [first, second] = out.yAxis as Record<string, Record<string, unknown>>[];
    expect(first?.splitLine).toEqual({ lineStyle: { color: '#333' } });
    expect(second?.axisLabel).toEqual({ color: '#f00' }); // the chart's own colour wins
    expect((out.legend as Record<string, unknown>).textStyle).toEqual({ color: '#eee' });
  });

  it('adds nothing a chart does not have', () => {
    expect(withTokenColours({ series: [] }, COLOURS)).toEqual({ series: [] });
  });

  it('QA 2026-11-11 V-03: a donut labels its slices in the theme text, with no dark halo', () => {
    const out = withTokenColours(
      { series: [{ type: 'pie', label: { show: true }, labelLine: { length: 12 } }] },
      { text: '#e6e6e6', secondary: '#aaaaaa', line: '#555555', grid: '#333333' },
    ) as { series: { label: Record<string, unknown>; labelLine: Record<string, unknown> }[] };
    const [pie] = out.series;
    expect(pie?.label).toMatchObject({ show: true, color: '#e6e6e6', textBorderWidth: 0 });
    expect(pie?.labelLine).toMatchObject({ length: 12, lineStyle: { color: '#555555' } });
  });
});
