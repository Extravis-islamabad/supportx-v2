import { describe, expect, it } from 'vitest';

import { kitOption, LARGE_SERIES } from './kit';

type Any = Record<string, unknown>;

function first(option: Any): Any {
  const [series] = option.series as Any[];
  if (series === undefined) throw new Error('no series');
  return series;
}

describe('chart kit (REQ-RPT-044)', () => {
  it('keeps a category colour on single-series bars and doughnut slices', () => {
    const input = {
      categories: ['P1', 'P2'],
      series: [{ name: 'Incidents', values: [3, 5] }],
      categoryColors: ['#c00', undefined],
    };
    const bar = kitOption({ ...input, type: 'bar' }) as Any;
    const barData = first(bar).data as Any[];
    expect(barData[0]).toEqual({ value: 3, itemStyle: { color: '#c00' } });
    const pie = kitOption({ ...input, type: 'doughnut' }) as Any;
    const slices = first(pie).data as Any[];
    expect(slices[0]).toMatchObject({ name: 'P1', value: 3, itemStyle: { color: '#c00' } });
  });

  it('stacks, fills areas and samples large line series', () => {
    const stacked = kitOption({
      type: 'stacked_bar',
      categories: ['a'],
      series: [
        { name: 'x', values: [1] },
        { name: 'y', values: [2] },
      ],
    }) as Any;
    expect((stacked.series as Any[]).every((s) => s.stack === 'total')).toBe(true);
    const many = Array.from({ length: LARGE_SERIES + 1 }, (_, i) => String(i));
    const area = kitOption({
      type: 'area',
      categories: many,
      series: [{ name: 'x', values: many.map(() => 1) }],
    }) as Any;
    const series = first(area);
    expect(series.areaStyle).toEqual({});
    expect(series.sampling).toBe('lttb');
  });

  it('draws a gauge from the first value with the given maximum', () => {
    const gauge = kitOption({
      type: 'gauge',
      categories: [],
      series: [{ name: 'Compliance', values: [93] }],
      max: 100,
    }) as Any;
    const series = first(gauge);
    expect(series.max).toBe(100);
    expect(series.data).toEqual([{ value: 93, name: 'Compliance' }]);
  });
});
