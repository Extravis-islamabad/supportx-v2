import { describe, expect, it } from 'vitest';

import { kitOption } from '@supportx/charts';

import { trend, visibleTrend } from './kpi';

// Full QA 2026-11-06, polish minors.

describe('QA6-DSH-01: a change too small to show is no change', () => {
  const minutes = (n: number) => `${String(Math.round(n))} min`;

  it('a 0.3 min change reads as the same, never worse in red', () => {
    expect(visibleTrend(trend(12.3, 12, 'down'), minutes)).toEqual({ delta: 0, good: null });
  });

  it('a change that shows keeps its verdict', () => {
    expect(visibleTrend(trend(15, 12, 'down'), minutes)).toEqual({ delta: 3, good: false });
  });
});

describe('QA6-RPT-02: doughnut labels keep apart', () => {
  it('hides a label that would still overlap and keeps a margin between them', () => {
    const option = kitOption({
      type: 'doughnut',
      categories: ['P1 - Critical', 'P2 - High'],
      series: [{ name: 'Open', values: [3, 4] }],
    }) as { series: { labelLayout?: { hideOverlap?: boolean }; label?: { minMargin?: number } }[] };
    expect(option.series[0]?.labelLayout?.hideOverlap).toBe(true);
    expect(option.series[0]?.label?.minMargin).toBeGreaterThan(0);
  });
});
