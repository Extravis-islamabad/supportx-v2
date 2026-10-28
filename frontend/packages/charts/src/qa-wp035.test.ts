import { describe, expect, it } from 'vitest';

import { kitOption, middleEllipsis, type KitChartType } from './kit';
import { mirrorForRtl } from './rtl';

// WP-035 QA findings on charts (~/Desktop/qa-wp035/QA-REPORT.md), one test per ID.

const AXIS_TYPES: KitChartType[] = ['bar', 'stacked_bar', 'line', 'area'];
const one = (type: KitChartType) =>
  kitOption({ type, categories: ['a', 'b'], series: [{ name: 'Incidents', values: [1, 2] }] });
const two = (type: KitChartType) =>
  kitOption({
    type,
    categories: ['a', 'b'],
    series: [
      { name: 'Open', values: [1, 2] },
      { name: 'Closed', values: [3, 4] },
    ],
  });

describe('QA WP-035', () => {
  it.each(AXIS_TYPES)('BUG-03: one measure has no legend in any direction (%s)', (type) => {
    for (const rtl of [false, true]) {
      expect(mirrorForRtl(one(type), rtl).legend).toBeUndefined();
    }
  });

  it.each(AXIS_TYPES)('BUG-03: a legend never overlaps the axis labels (%s)', (type) => {
    for (const rtl of [false, true]) {
      const option = mirrorForRtl(two(type), rtl) as {
        legend: { bottom: number };
        grid: { bottom: number; containLabel: boolean };
      };
      expect(option.legend.bottom).toBe(0);
      // The plot (with its axis labels, containLabel) ends above the legend's row.
      expect(option.grid.containLabel).toBe(true);
      expect(option.grid.bottom).toBeGreaterThanOrEqual(40);
    }
  });

  it('BUG-03: a doughnut keeps its slices clear of its legend', () => {
    const option = kitOption({
      type: 'doughnut',
      categories: ['a', 'b'],
      series: [{ name: 'Incidents', values: [1, 2] }],
    }) as { series: { center: [string, string]; radius: [string, string] }[] };
    const [, y] = option.series[0]?.center ?? ['50%', '50%'];
    const [, outer] = option.series[0]?.radius ?? ['0%', '100%'];
    expect(parseFloat(y) + parseFloat(outer) / 2).toBeLessThanOrEqual(80);
  });

  it('BUG-06: long names are shortened in the middle and stay apart; the full name is kept', () => {
    const alpha = 'QA35 789430 Customer Support Alpha';
    const beta = 'QA35 789430 Customer Support Beta';
    expect(middleEllipsis(alpha, 20)).not.toBe(middleEllipsis(beta, 20));
    expect(middleEllipsis(alpha, 20)).toContain('…');
    expect(middleEllipsis(alpha, 20).length).toBeLessThanOrEqual(20);
    expect(middleEllipsis('Short', 20)).toBe('Short');
    const option = kitOption({
      type: 'bar',
      categories: [alpha, beta],
      series: [{ name: 'Incidents', values: [1, 2] }],
    }) as { xAxis: { data: string[]; axisLabel: { formatter: (v: string) => string } } };
    // The axis shows the short form; the data (tooltip, table) keeps the full name.
    expect(option.xAxis.data).toEqual([alpha, beta]);
    const shown = [alpha, beta].map((v) => option.xAxis.axisLabel.formatter(v));
    expect(new Set(shown).size).toBe(2);
  });
});
