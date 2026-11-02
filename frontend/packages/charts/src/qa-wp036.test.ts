import { describe, expect, it } from 'vitest';

import { kitOption } from './kit';

// WP-036 QA round (~/Desktop/qa-wp036/QA-REPORT.md): one failing test per finding, then the fix.

/** The parts of a doughnut's option this test reads. */
interface Doughnut {
  legend: { type: string };
  series: { label: { show: boolean } }[];
}

describe('WP-036 QA', () => {
  it('C1: a narrow doughnut leaves names to its legend, which wraps instead of paging', () => {
    const input = {
      type: 'doughnut' as const,
      categories: ['P1 – Critical', 'P2 – High', 'P3 – Medium', 'P4 – Low'],
      series: [{ name: 'Incidents', values: [1, 2, 3, 4] }],
    };
    const narrow = kitOption({ ...input, compact: true }) as unknown as Doughnut;
    expect(narrow.series[0]?.label.show).toBe(false); // no "P…" cut slice labels
    expect(narrow.legend.type).toBe('plain'); // every name whole, no "1/4"
    const wide = kitOption(input) as unknown as Doughnut;
    expect(wide.series[0]?.label.show).toBe(true); // wide widgets and the report keep labels
  });
});
